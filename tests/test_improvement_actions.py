"""Automatic improvement actions and the closed loop (PRD FR-4.4)."""


def recompute_after_correction(db, correction: str) -> None:
    """Unlock the worked example's SEE through an approved request, correct marks, lock, recompute."""
    db.execute("""
        INSERT INTO app_user (user_id, username, password_hash, role, faculty_id) VALUES
            (1, 'fac', 'x', 'faculty', 1), (2, 'hod', 'x', 'admin', NULL) ON CONFLICT DO NOTHING;
        INSERT INTO unlock_request (assessment_id, requested_by, reason, status, decided_by, decided_at)
        VALUES (1, 1, 'CO3 marks were entered from the wrong sheet', 'approved', 2, now());
    """)
    db.execute("UPDATE assessment SET locked = false WHERE assessment_id = 1")
    db.execute(correction)
    db.execute("UPDATE assessment SET locked = true WHERE assessment_id = 1")
    db.execute("CALL sp_compute_attainment(1)")


def co3_action(db):
    return db.execute("SELECT status, description FROM improvement_action "
                      "WHERE offering_id = 1 AND co_id = 3 AND source = 'auto'").fetchone()


def test_recompute_closes_the_action_of_a_co_now_at_target(db):
    db.execute("CALL sp_compute_attainment(1)")
    assert co3_action(db)[0] == "open"                      # CO3 at 0.40
    recompute_after_correction(db, "UPDATE student_question_mark SET marks_obtained = 9 WHERE question_id = 3")
    status, text = co3_action(db)
    assert status == "done" and text == "CO3 final level 2.80 meets the target 2.00 after a recompute"


def test_recompute_updates_the_text_of_an_action_still_below_target(db):
    db.execute("CALL sp_compute_attainment(1)")
    # 33 of 60 now reach 60% on CO3: 55% -> direct level 1 -> final (80 x 1 + 20 x 2) / 100
    recompute_after_correction(db, "UPDATE student_question_mark SET marks_obtained = 6 "
                                   "WHERE question_id = 3 AND enrollment_id <= 33")
    assert co3_action(db) == ("open", "CO3 final level 1.20 is below the target 2.00")
