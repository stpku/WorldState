"""Guard the synthetic natural-language benchmark against false passes."""
from benchmarks.ws_agent.run import score


def test_unsupported_parameter_does_not_prove_angle_conflict(tmp_path):
    task={'id':'A19','kind':'reject','reason':'ANGULAR_CONSTRAINT_CONFLICT'}
    result=score(task,{},[],'发生垂直约束冲突',['unsupported element parameter'],tmp_path)
    assert result['status']=='FAIL'
    checked=score(task,{},[],'发生垂直约束冲突',['ANGULAR_CONSTRAINT_CONFLICT'],tmp_path)
    assert checked['status']=='PASS'
