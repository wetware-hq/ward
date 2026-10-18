"""Patient id mapping at the letters boundary (bindi case_id stays canonical in the harness)."""

from ward.patient_id import case_id_from_letters_patient, canonical_patient_id, letters_patient_id


def test_imm_case_id_round_trip():
    for case_id in ("SYNTH-IMM-001", "SYNTH-IMM-FOO.BAR_1"):
        assert canonical_patient_id(case_id) == case_id
        mapped = letters_patient_id(case_id)
        assert case_id_from_letters_patient(mapped) == case_id
        assert letters_patient_id(case_id_from_letters_patient(mapped)) == mapped


def test_non_imm_ids_pass_through():
    pid = "SYNTH-P1501"
    assert letters_patient_id(pid) == pid
    assert case_id_from_letters_patient(pid) == pid
