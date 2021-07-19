import pytest
from .util import write_profile_data, ProjectDefinition, built_schema, run_dbt

# ** goals of moving tests to pytest **
# - readability
# - being explicit and intentional
# - less friction to create
# - easier to debug
# - ability to "eject" test and create a real dbt project

# ** BEFORE **
# ripped from `test/integration/test_simple_seed`
# @use_profile('postgres')
# def test_postgres_simple_seed(self):
#     self._seed_and_run()

#     # this should truncate the seed_actual table, then re-insert.
#     self._after_seed_model_state(['seed'], exists=True)

# ** AFTER **
# an explicit example of converting an exisiting integration test to using pytest
@pytest.mark.supported('postgres')
def test_postgres_simple_seed(
    project_root, profiles_root, dbt_profile_data, unique_schema
):
    # write profile
    write_profile_data(profiles_root, dbt_profile_data)
    # setup project
    project = ProjectDefinition(
        project_data={'seeds': {'config': {'quote_columns': False}}},
        seeds={'data.csv': 'a,b\n1,hello\n2,goodbye'},
    )
    # write project
    project.write_to(project_root)
    # setup database
    built_schema_ctx = built_schema(unique_schema, project_root, profiles_root)
    # run tests
    with built_schema_ctx:
        results, success = run_dbt(['seed'], profiles_root)
        assert success == True
        assert len(results['results']) == 1

