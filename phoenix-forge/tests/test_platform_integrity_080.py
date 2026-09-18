import zipfile
from phoenix_forge.modules import archive_integrity,system_inventory,production_benchmark
from phoenix_forge.models import StressResult

def test_archive_integrity_accepts_valid_zip_regardless_of_small_size(tmp_path):
    path=tmp_path/'small.zip'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('payload.txt','phoenix'*1000)
    result=archive_integrity.inspect_zip(str(path))
    assert result['passed'] and result['sha256'] and result['member_count']==1

def test_archive_integrity_rejects_path_traversal(tmp_path):
    path=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('../escape.txt','blocked')
    result=archive_integrity.inspect_zip(str(path))
    assert result['status']=='FAILED'
    assert 'PATH_TRAVERSAL' in {x['code'] for x in result['issues']}

def test_archive_integrity_handles_missing_path(tmp_path):
    assert archive_integrity.inspect_zip(str(tmp_path/'missing.zip'))['status']=='NOT_FOUND'

def test_system_inventory_has_machine_and_cache_schema():
    result=system_inventory.collect()
    assert result['schema']=='phoenix.forge.system-inventory/v1'
    assert result['logical_cpus']>=1 and isinstance(result['caches'],list)

def test_production_benchmark_requires_repeatable_correct_runs(monkeypatch):
    def fake(*args,**kwargs):
        kind=args[0]
        value={'cpu':100.0,'memory':25.0,'cache':9.0}[kind]
        key={'cpu':'operations_per_second','memory':'bandwidth_gbps','cache':'million_accesses_per_second'}[kind]
        return StressResult(module=kind,passed=True,duration_s=.1,metrics={key:value})
    monkeypatch.setattr(production_benchmark.native_benchmark,'execute',fake)
    result=production_benchmark.run('quick')
    assert result['score_valid'] and all(x['stable'] for x in result['benchmarks'])
