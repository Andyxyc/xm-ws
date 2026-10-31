#!/usr/bin/env python3
"""Exercise the actual AK3 backend main sequence with explicit Linux test doubles.

No boot writer or packaged ELF executes. Kernel execution is an instrumented
shell mock. This validates official-manager arguments, output transport, one
entry invocation and failure propagation; not phone flashing or boot acceptance.
Run: python3 test_official_ak3_entry_linux.py --ak3 /path/to/prepared/AK3
"""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, socket, subprocess, sys, tempfile, zipfile

def digest(b): return hashlib.sha256(b).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ak3',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('official-ak3-entry-report.json'))
    a=p.parse_args()
    if sys.platform!='linux':raise RuntimeError('Linux shell/socket test only; do not start WSL')
    source=a.ak3.resolve(strict=True)
    binary=source/'META-INF/com/google/android/update-binary'
    core=source/'tools/ak3-core.sh'
    original=binary.read_bytes();core_before=core.read_bytes()
    text=original.decode()
    main_marker='show_progress 1.34 25;'
    assert text.count(main_marker)==1
    # Use the actual candidate UI function, without sourcing core's device setup.
    core_text=core_before.decode()
    m=re.search(r'(?m)^ui_print\(\) \{\n.*?^\}',core_text,re.S)
    assert m,'Core UI function not found'
    ui_function=m.group(0)
    root=Path(tempfile.mkdtemp(prefix='official-ak3-entry-'))
    report={'status':'IN_PROGRESS','backend_sha256':digest(original),'core_sha256':digest(core_before),
            'scope':'actual backend main sequence and candidate UI function; explicit host setup/kernel mocks',
            'not_tested':['packaged ARM64 tools','boot unpack/repack','block writer','phone Root/REC','kernel boot'], 'cases':[]}
    shell=shutil.which('bash');assert shell
    assert shutil.which('unzip')
    stubs=r'''
# Explicit host-only doubles; real Android mount/device operations do not run.
setup_bb() { mkdir -p "$AKHOME/bin"; ln -s "$TEST_SHELL" "$AKHOME/bin/ash"; }
setup_env() { :; }
restore_env() { :; }
do_devicecheck() { :; }
do_versioncheck() { :; }
do_levelcheck() { :; }
do_vendorlevelcheck() { :; }
do_modules() { :; }
debugging() { :; }
cleanup() {
  case "$AKHOME" in "$TEST_CASE"/kernel) rm -rf "$AKHOME" ;; *) exit 99 ;; esac
}
'''
    backend=text.replace(main_marker,stubs+'\n'+main_marker,1)
    for mode,transport,rc in [('android','pipe',0),('android','socket',0),
            ('android','pipe',42),('android','socket',42),('recovery','pipe',0),('recovery','pipe',42)]:
        case=root/f'{mode}-{transport}-{rc}';case.mkdir()
        fakebin=case/'fakebin';fakebin.mkdir()
        ps=fakebin/'ps';ps.write_text('#!/bin/sh\n'+("echo '123 zygote64'\n" if mode=='android' else 'exit 0\n'),encoding='utf-8',newline='\n');ps.chmod(0o755)
        entry=case/'update-binary';entry.write_text(backend,encoding='utf-8',newline='\n')
        image=case/'kernel.zip'
        fixture='''properties() { '\n+kernel.string=Host mock kernel fixture\n+do.cleanup=1\n+do.cleanuponabort=0\n+'; }\n+'''.replace('\n+','\n')+ui_function+r'''
ui_print "心中都是墨"
printf 'called\n' >> "$TEST_CALLS"
if [ "$TEST_KERNEL_RC" -ne 0 ]; then ui_print "Injected writer failure"; fi
exit "$TEST_KERNEL_RC"
'''
        with zipfile.ZipFile(image,'w') as z:
            z.writestr('anykernel.sh',fixture)
            z.writestr('tools/host-fixture.txt','No packaged binaries execute.\n')
        env=os.environ.copy()
        env.update(PATH=str(fakebin)+':'+env['PATH'],AKHOME=str(case/'kernel'),
            POSTINSTALL=str(case/'manager-session'),TEST_CASE=str(case),TEST_SHELL=shell,
            TEST_CALLS=str(case/'calls'),TEST_KERNEL_RC=str(rc))
        env.pop('AK3_STDOUT_UI',None);env.pop('BOOTMODE',None)
        # Matches official HorizonKernelWorker.flash(): sh entry 3 1 zip slot.
        command=[shell,str(entry),'3','1',str(image),'a']
        if transport=='socket':
            parent,child=socket.socketpair()
            proc=subprocess.Popen(command,env=env,stdout=child,stderr=child)
            child.close();chunks=[];parent.settimeout(15)
            while True:
                b=parent.recv(65536)
                if not b:break
                chunks.append(b)
            parent.close();result_code=proc.wait(timeout=15);output=b''.join(chunks).decode(errors='replace')
        else:
            r=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
            result_code=r.returncode;output=r.stdout.decode(errors='replace')
        (case/'output.txt').write_text(output)
        # The official UI discards every non-ui_print-prefixed line.
        visible=[l.removeprefix('ui_print').strip() for l in output.splitlines() if l.startswith('ui_print')]
        calls=(case/'calls').read_text().splitlines() if (case/'calls').exists() else []
        checks={'kernel_mock_called_once':calls==['called'],
            'return_status_propagated':(result_code==0)==(rc==0),
            'banner_visible_to_official_parser':'心中都是墨' in visible,
            'no_fd_reopen_errors':not any(x in output for x in ['No such device or address','cannot create /proc/self/fd','can\'t create /proc/self/fd']),
            'no_done_after_error':rc==0 or 'Done!' not in visible}
        report['cases'].append({'mode':mode,'transport':transport,'injected_kernel_rc':rc,
            'entry_rc':result_code,'pass':all(checks.values()),'checks':checks,'visible_lines':visible,'log_tail':output[-1500:]})
    report['source_unchanged']=binary.read_bytes()==original and core.read_bytes()==core_before
    report['status']='PASS_OFFICIAL_ARGUMENTS_UI_TRANSPORT_AND_RC_WITH_MOCK_KERNEL' if (
        report['source_unchanged'] and all(c['pass'] for c in report['cases'])) else 'FAIL_ENTRY_MOCK_CASES'
    report['fixture_root']=str(root)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'cases':len(report['cases']),
        'failed':[{'mode':c['mode'],'transport':c['transport'],'rc':c['injected_kernel_rc'],'checks':c['checks']} for c in report['cases'] if not c['pass']],
        'report':str(a.output)},ensure_ascii=False))
    return 0 if report['status'].startswith('PASS_') else 1

if __name__=='__main__':sys.exit(main())
