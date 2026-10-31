from pathlib import Path
import json,hashlib,shutil,urllib.request,os
r=Path('retained/build-result')
expected={'Image.raw':'53b418b42101dff744619772f9b1f2222483b6a15f1c5d4e5522bcd5ffa5d490','Module.symvers':'9ce7565cd93e1351a3ecfce3f4355440350de2105d578d9b513f084b9364563d','System.map':'a9183b5f4d45aced85d21a8f8dff853cae522b357a9b382ab0220981ff021089','.config':'c4509ec7bed8c704c5f19943c86bbfdcb8fa2a5f1ed8a21bf6dabdb18d6681ac'}
for f,h in expected.items():assert hashlib.sha256((r/f).read_bytes()).hexdigest()==h,f
shutil.copytree(r,'build-result')
out=Path('kernel-work/common/out');out.mkdir(parents=True)
for f in ['.config','System.map','Module.symvers']:shutil.copyfile(r/f,out/f)
k=Path('kernel-work/KernelSU/kernel');k.mkdir(parents=True)
data=urllib.request.urlopen('https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/b16e899a555e9b96aa1225f049cd7274820ca5b8/kernel/Kconfig',timeout=30).read()
assert b'config KPM' in data and b'config KSU_SUSFS' in data
(k/'Kconfig').write_bytes(data)
p=Path('build-result/source-provenance.json');v=json.loads(p.read_text())
v.update(compilation_run=41230343313,compilation_commit='4313b7471c6303e81117b5f8a8880eb38cda1e50',packaging_commit=os.environ['GITHUB_SHA'],kernel_compilation_reused_without_changes=True,stability_backport_708f_in_this_compilation=False,fast_candidate=True,not_a_device_verified_release=True)
p.write_text(json.dumps(v,indent=2)+'\n')
print('Original completed Image/config/map/symvers SHA verified. No kernel compilation.')
