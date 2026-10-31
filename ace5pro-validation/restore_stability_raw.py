from pathlib import Path
import hashlib,json,os,shutil,urllib.request
r=Path('retained/build-result')
v=json.loads((r/'source-provenance.json').read_text())
assert v['kernel_pin']=='9a56e8288fc62e2047a142114faeb9467447311d'
assert v['sukisu_pin']=='b16e899a555e9b96aa1225f049cd7274820ca5b8'
assert v['susfs_upstream']=='93114563fd6b08092b9ce8c0309738c921ac8bd1'
assert v['builtin_backports'][0]['patch_sha256']=='b54b4161def9aadfe679a527370c31c5625759e8a36d46384e512891dde31e39'
assert 'fput(orig_file);' in (r/'sukisu-source.patch').read_text()
raw=(r/'Image.raw').read_bytes()
assert raw[56:60]==b'ARMd' and len(raw)>10000000
assert hashlib.sha256(raw).hexdigest()!='53b418b42101dff744619772f9b1f2222483b6a15f1c5d4e5522bcd5ffa5d490'
shutil.copytree(r,'build-result')
out=Path('kernel-work/common/out');out.mkdir(parents=True)
for f in ['.config','System.map','Module.symvers']:shutil.copyfile(r/f,out/f)
k=Path('kernel-work/KernelSU/kernel');k.mkdir(parents=True)
data=urllib.request.urlopen('https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/b16e899a555e9b96aa1225f049cd7274820ca5b8/kernel/Kconfig',timeout=30).read()
assert b'config KPM' in data and b'config KSU_SUSFS' in data
(k/'Kconfig').write_bytes(data)
v.update(compilation_run=41231027191,compilation_commit='6c7f14d75296e8e9971053e260f761bba6a8c541',packaging_commit=os.environ['GITHUB_SHA'],kernel_compilation_reused_without_changes=True,stability_backport_708f_in_this_compilation=True,not_a_device_verified_release=True)
Path('build-result/source-provenance.json').write_text(json.dumps(v,indent=2)+'\n')
print('Real completed stability compilation restored; corrected KPM and packaging only.')
