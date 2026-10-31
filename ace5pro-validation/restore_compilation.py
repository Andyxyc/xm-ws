from pathlib import Path
import json,shutil,hashlib,urllib.request,os
r=Path('retained/build-result')
assert (r/'Image.raw').is_file(),'The source build did not complete an Image; inspect its real failure log.'
assert (r/'Image.kpm').is_file() and (r/'kpm-entry.json').is_file(),'KPM postprocess did not pass; retain raw compile and repair that stage.'
j=json.loads((r/'kpm-entry.json').read_text())
assert j['status']=='PASS_STATIC_KPM_ABI2_STRUCTURE_AND_LINKER_ANCHORS'
assert hashlib.sha256((r/'Image.kpm').read_bytes()).hexdigest()==j['patched']['sha256']
assert hashlib.sha256((r/'Image.raw').read_bytes()).hexdigest()==j['before']['sha256']
shutil.copytree(r,'build-result')
out=Path('kernel-work/common/out');out.mkdir(parents=True)
shutil.copyfile(r/'.config',out/'.config')
shutil.copyfile(r/'System.map',out/'System.map')
ksu=Path('kernel-work/KernelSU/kernel');ksu.mkdir(parents=True)
url='https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/b16e899a555e9b96aa1225f049cd7274820ca5b8/kernel/Kconfig'
data=urllib.request.urlopen(url,timeout=30).read();assert b'config KPM' in data and b'config KSU_SUSFS' in data
(ksu/'Kconfig').write_bytes(data)
p=Path('build-result/source-provenance.json');v=json.loads(p.read_text())
v.update(compilation_run=41231027191,compilation_commit='6c7f14d75296e8e9971053e260f761bba6a8c541',packaging_commit=os.environ['GITHUB_SHA'],kernel_compilation_reused_without_changes=True)
p.write_text(json.dumps(v,indent=2)+'\n')
print('Retained raw Image and paired KPM SHA verified; no kernel rebuild.')
