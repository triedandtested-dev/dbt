from mock import MagicMock
import os
import six
import unittest

import dbt.compilation
import dbt.model
import dbt.project
import dbt.templates
import dbt.utils

import networkx as nx

from dbt.logger import GLOBAL_LOGGER as logger

class FakeArgs:
    
    def __init__(self):
        self.full_refresh = False

class GraphTest(unittest.TestCase):

    def tearDown(self):
        nx.write_yaml = self.real_write_yaml
        dbt.utils.dependency_projects = self.real_dependency_projects
        dbt.clients.system.find_matching = self.real_find_matching
        dbt.clients.system.load_file_contents = self.real_load_file_contents

    def setUp(self):
        def mock_write_yaml(graph, outfile):
            self.graph_result = graph

        self.real_write_yaml = nx.write_yaml
        nx.write_yaml = mock_write_yaml

        self.graph_result = None

        self.profiles = {
            'test': {
                'outputs': {
                    'test': {
                        'type': 'postgres',
                        'threads': 4,
                        'host': 'database',
                        'port': 5432,
                        'user': 'root',
                        'pass': 'password',
                        'dbname': 'dbt',
                        'schema': 'dbt_test'
                    }
                },
                'target': 'test'
            }
        }

        self.real_dependency_projects = dbt.utils.dependency_projects
        dbt.utils.dependency_projects = MagicMock(return_value=[])

        self.mock_models = []
        self.mock_content = {}

        def mock_find_matching(root_path, relative_paths_to_search,
                               file_pattern):
            if 'sql' not in file_pattern:
                return []

            to_return = []

            if 'models' in relative_paths_to_search:
                to_return = to_return + self.mock_models

            return to_return

        self.real_find_matching = dbt.clients.system.find_matching
        dbt.clients.system.find_matching = MagicMock(
            side_effect=mock_find_matching)

        def mock_load_file_contents(path):
            return self.mock_content[path]

        self.real_load_file_contents = dbt.clients.system.load_file_contents
        dbt.clients.system.load_file_contents = MagicMock(
            side_effect=mock_load_file_contents)

    def get_project(self, extra_cfg=None):
        if extra_cfg is None:
            extra_cfg = {}

        cfg = {
            'name': 'test_models_compile',
            'version': '0.1',
            'profile': 'test',
            'project-root': os.path.abspath('.'),
        }
        cfg.update(extra_cfg)

        project = dbt.project.Project(
            cfg=cfg,
            profiles=self.profiles,
            profiles_dir=None)

        project.validate()
        return project

    def get_compiler(self, project):
        compiler = dbt.compilation.Compiler(
            project,
            dbt.templates.BaseCreateTemplate,
            FakeArgs())

        compiler.get_macros = MagicMock(return_value=[])
        return compiler

    def use_models(self, models):
        for k, v in models.items():
            path = os.path.abspath('models/{}.sql'.format(k))
            self.mock_models.append({
                'searched_path': 'models',
                'absolute_path': path,
                'relative_path': '{}.sql'.format(k)})
            self.mock_content[path] = v

    def test__single_model(self):
        self.use_models({
            'model_one': 'select * from events',
        })

        compiler = self.get_compiler(self.get_project())
        compiler.compile(limit_to=['models'])

        self.assertEquals(
            self.graph_result.nodes(),
            [('test_models_compile', 'model_one')])

        self.assertEquals(
            self.graph_result.edges(),
            [])

    def test__two_models_simple_ref(self):
        self.use_models({
            'model_one': 'select * from events',
            'model_two': "select * from {{ref('model_one')}}",
        })

        compiler = self.get_compiler(self.get_project())
        compiler.compile(limit_to=['models'])

        six.assertCountEqual(self,
            self.graph_result.nodes(),
            [('test_models_compile', 'model_one'),
             ('test_models_compile', 'model_two'),])

        six.assertCountEqual(self,
            self.graph_result.edges(),
            [(('test_models_compile', 'model_one'),
              ('test_models_compile', 'model_two')),])

    def test__model_materializations(self):
        self.use_models({
            'model_one': 'select * from events',
            'model_two': "select * from {{ref('model_one')}}",
            'model_three': "select * from events",
            'model_four': "select * from events",
        })

        cfg = {
            "models": {
                "materialized": "table",
                "test_models_compile": {
                    "model_one": { "materialized": "table" },
                    "model_two": { "materialized": "view" },
                    "model_three": { "materialized": "ephemeral" }
                }
            }
        }

        compiler = self.get_compiler(self.get_project(cfg))
        compiler.compile(limit_to=['models'])

        expected_materialization = {
            "model_one": "table",
            "model_two": "view",
            "model_three": "ephemeral",
            "model_four": "table"
        }

        nodes = self.graph_result.node

        for model, expected in expected_materialization.items():
            actual = nodes[("test_models_compile", model)]["materialized"]
            self.assertEquals(actual, expected)


    def test__model_enabled(self):
        self.use_models({
            'model_one': 'select * from events',
            'model_two': "select * from {{ref('model_one')}}",
        })

        cfg = {
            "models": {
                "materialized": "table",
                "test_models_compile": {
                    "model_one": { "enabled": True },
                    "model_two": { "enabled": False },
                }
            }
        }

        compiler = self.get_compiler(self.get_project(cfg))
        compiler.compile(limit_to=['models'])


        six.assertCountEqual(self,
            self.graph_result.nodes(), [('test_models_compile', 'model_one')])

        six.assertCountEqual(self, self.graph_result.edges(), [])

    def test__model_incremental_without_sql_where_fails(self):
        self.use_models({
            'model_one': 'select * from events'
        })

        cfg = {
            "models": {
                "materialized": "table",
                "test_models_compile": {
                    "model_one": { "materialized": "incremental" },
                }
            }
        }

        compiler = self.get_compiler(self.get_project(cfg))

        with self.assertRaises(RuntimeError) as context:
            compiler.compile(limit_to=['models'])

    def test__model_incremental(self):
        self.use_models({
            'model_one': 'select * from events'
        })

        cfg = {
            "models": {
                "test_models_compile": {
                    "model_one": {
                        "materialized": "incremental",
                        "sql_where": "TRUE",
                        "unique_key": "TRUE"
                    },
                }
            }
        }

        compiler = self.get_compiler(self.get_project(cfg))
        compiler.compile(limit_to=['models'])

        node = ('test_models_compile', 'model_one')

        self.assertEqual(self.graph_result.nodes(), [node])
        self.assertEqual(self.graph_result.edges(), [])

        self.assertEqual(
                self.graph_result.node[node]['materialized'],
                'incremental')

