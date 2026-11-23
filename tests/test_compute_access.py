"""Who may run the attainment engine (PRD Section 3, NFR-5). Connections act as the API does:
the copo_api login with SET ROLE copo_<role> and the app.* settings."""

from tests.conftest import raises_sqlstate


def results(db):
    return db.execute("SELECT count(*) FROM co_attainment").fetchone()[0]


def test_faculty_computes_only_their_own_offering(db, api_connect):
    with raises_sqlstate("42501"):
        api_connect("faculty", faculty_id=2).execute("CALL sp_compute_attainment(1)")
    api_connect("faculty", faculty_id=1).execute("CALL sp_compute_attainment(1)")
    assert results(db) == 3


def test_app_role_setting_alone_does_not_make_an_admin(db, api_connect):
    spoofed = api_connect("faculty", faculty_id=2, app_role="admin")   # active role is copo_faculty
    with raises_sqlstate("42501"):
        spoofed.execute("CALL sp_compute_attainment(1)")
    assert results(db) == 0


def test_students_and_coordinators_cannot_compute(db, api_connect):
    for role in ("student", "coordinator"):
        with raises_sqlstate("42501"):                                 # no EXECUTE privilege
            api_connect(role).execute("CALL sp_compute_attainment(1)")


def test_only_admin_refreshes_dashboards_or_computes_everything(db, api_connect):
    faculty = api_connect("faculty", faculty_id=1)
    with raises_sqlstate("42501"):
        faculty.execute("SELECT fn_refresh_dashboards()")
    with raises_sqlstate("42501"):
        faculty.execute("CALL sp_compute_all()")
    admin = api_connect("admin")
    admin.execute("CALL sp_compute_all()")
    admin.execute("SELECT fn_refresh_dashboards()")
    assert results(db) == 3
