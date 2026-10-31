from pathlib import Path
import ast,urllib.request
r=Path('ace5pro666/package.py');tree=ast.parse(r.read_text())
values={}
for node in tree.body:
    if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('before','ui_before','ui_after','progress_before','progress_after'):
        values[node.targets[0].id]=ast.literal_eval(node.value)
out=Path('entry-check');out.mkdir()
for target,upstream in [('update-binary','META-INF/com/google/android/update-binary'),('ak3-core.sh','tools/ak3-core.sh')]:
    url='https://raw.githubusercontent.com/osm0sis/AnyKernel3/41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1/'+upstream
    body=urllib.request.urlopen(url,timeout=30).read().decode()
    if target=='ak3-core.sh':
        assert body.count(values['before'])==1
        body=body.replace(values['before'],'  ace_flash_boot "$BLOCK" "$BOOTIMG" "$AKHOME/boot-new.img";',1)
    assert body.count(values['ui_before'])==1
    body=body.replace(values['ui_before'],values['ui_after'],1)
    if target=='update-binary':
        assert body.count(values['progress_before'])==1
        body=body.replace(values['progress_before'],values['progress_after'],1)
    (out/target).write_text(body)
    nested=out/('META-INF/com/google/android/update-binary' if target=='update-binary' else 'tools/ak3-core.sh')
    nested.parent.mkdir(parents=True,exist_ok=True)
    nested.write_text(body)
print('Exact pinned backend/core transformed with the actual packaging source.')
