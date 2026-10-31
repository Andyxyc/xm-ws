#!/usr/bin/env python3
"""Pure shell tests of the actual two AK3 ui_print functions; no ELF/device I/O.

python test_ak3_ui_output.py --backend update-binary --core ak3-core.sh --output report.json
Uses installed bash (Git Bash is supported on Windows); never starts WSL.
"""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, socket, subprocess, sys, tempfile

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',type=Path,required=True)
    p.add_argument('--core',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    candidates=([r'C:/Program Files/Git/bin/bash.exe'] if os.name=='nt' else [])+[shutil.which('bash')]
    bash=next((str(Path(x).resolve()) for x in candidates if x and Path(x).is_file()),None)
    if not bash:raise RuntimeError('An existing bash is required; no shell will be installed')
    a.output=a.output.resolve();a.output.parent.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='ak3-ui-',dir=a.output.parent))
    report={'scope':'actual extracted ui_print shell functions only; no packaged ELF or phone actions',
            'shell':bash,'cases':[],'sources':[]}
    for label,path in [('update-binary',a.backend),('ak3-core.sh',a.core)]:
        blob=path.read_bytes();text=blob.decode('utf-8')
        m=re.search(r'(?m)^ui_print\(\) \{\n.*?^\}',text,re.S)
        assert m,'ui_print missing: '+str(path)
        fn=m.group(0)
        report['sources'].append({'file':str(path.resolve()),'sha256':hashlib.sha256(blob).hexdigest(),
            'ui_function_sha256':hashlib.sha256(fn.encode()).hexdigest()})
        for fd in (1,3):
            script=root/(label.replace('.','_')+f'-fd{fd}.sh')
            captured=root/(label.replace('.','_')+f'-fd{fd}.txt')
            # No path interpolation in shell text; output path is a positional argument.
            script.write_text(fn+'\n'+('exec 3>"$1"\n' if fd==3 else '')+
                f'OUTFD={fd}\nui_print "心中都是墨" "Ready"\n',encoding='utf-8',newline='\n')
            result=subprocess.run([bash,str(script),str(captured)],capture_output=True)
            stderr=result.stderr.decode(errors='replace')
            output=(captured.read_bytes() if fd==3 and captured.exists() else result.stdout).decode(errors='replace')
            visible=[line.removeprefix('ui_print').strip() for line in output.splitlines() if line.startswith('ui_print')]
            checks={'rc_zero':result.returncode==0,'chinese_visible_to_official_parser':'心中都是墨' in visible,
                    'english_visible_to_official_parser':'Ready' in visible,'no_fd_error':not stderr,
                    'REC_nonstdout_route_preserved':fd==1 or not result.stdout}
            report['cases'].append({'function':label,'fd':fd,'transport':'stdout-pipe' if fd==1 else 'Recovery-file-fd3',
                'pass':all(checks.values()),'checks':checks,'raw_output':output,'stderr':stderr})
        if sys.platform=='linux':
            script=root/(label.replace('.','_')+'-socket.sh')
            script.write_text(fn+'\nOUTFD=1\nui_print "心中都是墨" "Ready"\n',encoding='utf-8',newline='\n')
            left,right=socket.socketpair()
            proc=subprocess.Popen([bash,str(script)],stdout=right,stderr=right)
            right.close();left.settimeout(10);parts=[]
            while True:
                b=left.recv(65536)
                if not b:break
                parts.append(b)
            left.close();rc=proc.wait(timeout=10);output=b''.join(parts).decode(errors='replace')
            visible=[line.removeprefix('ui_print').strip() for line in output.splitlines() if line.startswith('ui_print')]
            checks={'rc_zero':rc==0,'chinese_visible_to_official_parser':'心中都是墨' in visible,
                    'english_visible_to_official_parser':'Ready' in visible,
                    'no_socket_reopen_error':'No such device or address' not in output and "can't create /proc" not in output}
            report['cases'].append({'function':label,'fd':1,'transport':'stdout-Unix-socket',
                'pass':all(checks.values()),'checks':checks,'raw_output':output})
        assert path.read_bytes()==blob,'Source changed during UI check'
    report['status']='PASS_REAL_UI_FUNCTIONS_AND_OFFICIAL_PREFIX_PARSER' if all(c['pass'] for c in report['cases']) else 'FAIL_UI_FUNCTION_CASES'
    report['windows_limit']='Unix-socket transport is tested only on Linux; Windows checks pipe and Recovery fd3.'
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'cases':len(report['cases']),
        'failed':[{'function':c['function'],'transport':c['transport'],'checks':c['checks']} for c in report['cases'] if not c['pass']],
        'report':str(a.output)},ensure_ascii=False))
    return 0 if report['status'].startswith('PASS_') else 1

if __name__=='__main__':sys.exit(main())
