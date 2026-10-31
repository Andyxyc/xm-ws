#!/usr/bin/env python3
"""Cloud-only real loop-device tests of the unmodified AK3 boot writer.

Run: sudo -E python3 test_ace_writer_linux.py --installer /absolute/ace-install.sh
Requires an ephemeral GitHub Linux runner with losetup/mount/mkfs.ext4/unshare.
No handset, stock image or physical block device is accepted as input.
This tests writer I/O and failure propagation, not Android boot or AK3 repacking.
"""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile

SIZE = 4 * 1024 * 1024

def sha(data):
    return hashlib.sha256(data).hexdigest()

def run(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, **kw)

def exe(name):
    value = shutil.which(name)
    if not value:
        raise RuntimeError('Required program missing: ' + name)
    return str(Path(value).resolve())

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--installer', type=Path, required=True)
    p.add_argument('--output', type=Path, default=Path('writer-loopback-report.json'))
    p.add_argument('--inside-private-mount-namespace', action='store_true')
    a = p.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0 or os.getenv('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Only root on an ephemeral GitHub Linux runner is supported')
    a.installer = a.installer.resolve(strict=True)
    a.output = a.output.resolve()
    if not a.inside_private_mount_namespace:
        return subprocess.run([exe('unshare'), '--mount', '--propagation', 'private',
            sys.executable, str(Path(__file__).resolve()), '--installer', str(a.installer),
            '--output', str(a.output), '--inside-private-mount-namespace']).returncode
    tools = {n: exe(n) for n in ('losetup', 'mount', 'umount', 'mkfs.ext4', 'dd',
                                 'sha256sum', 'cp', 'sync', 'blockdev', 'bash', 'sh')}
    source = a.installer.read_bytes()
    root = Path(tempfile.mkdtemp(prefix='ace-writer-loop-', dir=os.getenv('RUNNER_TEMP')))
    loops = []
    mounted = False
    report = {'status': 'IN_PROGRESS', 'installer_sha256': sha(source),
              'scope': 'actual source function + ext4 persistent backup + disposable loop block device',
              'not_tested': ['AK3 repack', 'Android manager/REC execution', 'phone writes',
                             'actual kernel boot', 'hardware stability'], 'cases': []}
    old = (bytes(range(256)) * (SIZE // 256))
    replacement = b'ANDROID!synthetic-boot-writer-fixture\x00' * 257
    expected = replacement + bytes(SIZE - len(replacement))
    try:
        # Bind mounts and /data are private to this process mount namespace.
        # All writable blocks are created from files directly below this unique root.
        volume = root / 'backup-filesystem.ext4'
        with volume.open('wb') as f:
            f.truncate(48 * 1024 * 1024)
        loop = subprocess.check_output([tools['losetup'], '--find', '--show', str(volume)], text=True).strip()
        loops.append(loop)
        actual = subprocess.check_output([tools['losetup'], '-n', '-O', 'BACK-FILE', loop], text=True).strip()
        assert Path(actual).resolve() == volume.resolve(), actual
        run([tools['mkfs.ext4'], '-q', '-F', loop])
        Path('/data').mkdir(exist_ok=True)
        run([tools['mount'], '-t', 'ext4', loop, '/data'])
        mounted = True
        boot = root / 'synthetic-boot-block.img'
        boot.write_bytes(old)
        block = subprocess.check_output([tools['losetup'], '--find', '--show', str(boot)], text=True).strip()
        loops.append(block)
        actual = subprocess.check_output([tools['losetup'], '-n', '-O', 'BACK-FILE', block], text=True).strip()
        assert Path(actual).resolve() == boot.resolve(), actual
        assert Path(block).name.startswith('loop') and Path(block).parent == Path('/dev')
        backups = Path('/data/adb/kernel-backups/OnePlus-Ace5-Pro')
        cases = [
            ('success', False, True),
            ('write_fail', True, True),
            ('partial_write_fail', True, True),
            ('read_fail', True, True),
            ('read_corrupt', True, True),
            ('read_short_success', True, True),
            ('backup_cp_fail', True, False),
            ('backup_corrupt', True, False),
            ('source_hash_fail', True, False),
            ('backup_hash_fail', True, False),
            ('both_backup_hashes_fail', True, False),
            ('both_backup_hashes_nonhex', True, False),
            ('new_image_hash_fail', True, False),
            ('readback_hash_fail', True, True),
            ('backup_sync_fail', True, False),
            ('after_write_sync_fail', True, True),
            ('oversize', True, False),
            ('unaligned_original', True, False),
            ('regular_file_instead_of_block', True, False),
            ('install_record_fail', True, True),
            ('install_record_sync_fail', True, True),
        ]
        for index, (name, expect_error, may_have_written) in enumerate(cases):
            case = root / ('%02d-%s' % (index, name))
            case.mkdir()
            original = case / 'original.img'
            original.write_bytes(old[:-1] if name == 'unaligned_original' else old)
            image = case / 'new.img'
            image.write_bytes(bytes(SIZE + 1) if name == 'oversize' else replacement)
            reset = case / 'reset.img'
            reset.write_bytes(old)
            run([tools['dd'], 'if=' + str(reset), 'of=' + block, 'bs=1048576',
                 'conv=fsync', 'status=none'])
            if backups.exists():
                shutil.rmtree(backups)
            wrappers = case / 'bin'
            wrappers.mkdir()
            def script(n, text):
                f = wrappers / n
                f.write_text('#!/bin/bash\nset -u\n' + text + '\n')
                f.chmod(0o755)
            script('dd', r'''
write=0; read=0
for a in "$@"; do
  [ "$a" = "of=$TEST_BLOCK" ] && write=1
  [ "$a" = "if=$TEST_BLOCK" ] && read=1
done
if [ "$write" = 1 ]; then
  printf W >> "$TEST_CASE/device-write-attempts"
  case "$TEST_KIND" in
    write_fail) exit 44 ;;
    partial_write_fail)
      "$REAL_DD" "if=$AKHOME/boot-write.img" "of=$TEST_BLOCK" bs=4096 count=1 conv=notrunc,fsync status=none
      exit 44 ;;
  esac
fi
if [ "$read" = 1 ]; then
  case "$TEST_KIND" in
    read_fail) exit 45 ;;
    read_short_success)
      exec "$REAL_DD" "if=$TEST_BLOCK" "of=$AKHOME/boot-readback.img" bs=4096 count=1 status=none ;;
    read_corrupt)
      "$REAL_DD" "$@" || exit $?
      printf '\xff' | "$REAL_DD" "of=$AKHOME/boot-readback.img" bs=1 count=1 conv=notrunc status=none
      exit 0 ;;
  esac
fi
exec "$REAL_DD" "$@"
''')
            script('cp', r'''
case "$TEST_KIND" in
  backup_cp_fail) exit 46 ;;
  backup_corrupt)
    "$REAL_CP" "$@" || exit $?
    printf '\xff' | "$REAL_DD" "of=${@: -1}" bs=1 count=1 conv=notrunc status=none
    exit 0 ;;
esac
exec "$REAL_CP" "$@"
''')
            script('sha256sum', r'''
is_source=0; is_backup=0; is_new=0; is_readback=0
[ "$1" = "$TEST_ORIGINAL" ] && is_source=1
case "$1" in /data/adb/kernel-backups/OnePlus-Ace5-Pro/*.img) is_backup=1 ;; esac
[ "$1" = "$AKHOME/boot-write.img" ] && is_new=1
[ "$1" = "$AKHOME/boot-readback.img" ] && is_readback=1
case "$TEST_KIND" in
  source_hash_fail) [ "$is_source" = 1 ] && exit 47 ;;
  backup_hash_fail) [ "$is_backup" = 1 ] && exit 47 ;;
  both_backup_hashes_fail) [ $((is_source + is_backup)) -gt 0 ] && exit 47 ;;
  both_backup_hashes_nonhex)
    if [ $((is_source + is_backup)) -gt 0 ]; then
      printf '%064d  %s\n' 0 "$1" | tr 0 z
      exit 0
    fi ;;
  new_image_hash_fail) [ "$is_new" = 1 ] && exit 47 ;;
  readback_hash_fail) [ "$is_readback" = 1 ] && exit 47 ;;
esac
exec "$REAL_SHA" "$@"
''')
            script('sync', r'''
n=0
[ -f "$TEST_CASE/sync-count" ] && n=$(cat "$TEST_CASE/sync-count")
n=$((n+1)); printf '%s' "$n" > "$TEST_CASE/sync-count"
case "$TEST_KIND:$n" in backup_sync_fail:1|after_write_sync_fail:2|install_record_sync_fail:3) exit 48 ;; esac
exec "$REAL_SYNC" "$@"
''')
            harness = case / 'run.sh'
            harness.write_text(r'''#!/bin/sh
ui_print() { echo "$*"; }
abort() { echo "ABORT: $*"; exit 1; }
printf() {
  case "$TEST_KIND:$1" in install_record_fail:partition=*) return 49 ;; esac
  command printf "$@"
}
. "$TEST_INSTALLER"
ace_flash_boot "$TARGET_BLOCK" "$TEST_ORIGINAL" "$TEST_IMAGE"
ui_print "Installation complete."
''')
            env = os.environ.copy()
            env.update(PATH=str(wrappers) + ':' + env['PATH'], TEST_KIND=name,
                TEST_CASE=str(case), AKHOME=str(case), TEST_BLOCK=block,
                TARGET_BLOCK=str(original) if name == 'regular_file_instead_of_block' else block,
                TEST_ORIGINAL=str(original), TEST_IMAGE=str(image),
                TEST_INSTALLER=str(a.installer), REAL_DD=tools['dd'], REAL_CP=tools['cp'],
                REAL_SHA=tools['sha256sum'], REAL_SYNC=tools['sync'])
            result = subprocess.run([tools['sh'], str(harness)], env=env,
                                    capture_output=True, text=True, timeout=35)
            log = result.stdout + result.stderr
            (case / 'output.txt').write_text(log)
            readback = subprocess.check_output([tools['dd'], 'if=' + block,
                           'bs=1048576', 'status=none'])
            records = list(backups.glob('*.img')) if backups.exists() else []
            verified_backup = bool(records) and all(p.read_bytes() == original.read_bytes() for p in records)
            wrote = (case / 'device-write-attempts').exists()
            checks = {
                'error_status_matches': (result.returncode != 0) == expect_error,
                'success_text_matches': ('Installation complete.' in log) == (not expect_error),
                'no_verified_success_after_failure': not expect_error or ' Boot verified.' not in log,
                'no_early_physical_write': may_have_written or not wrote,
                'untouched_when_failure_precedes_write': may_have_written or readback == old,
            }
            if name == 'success':
                checks.update(full_expected_padded_image_written=readback == expected,
                              complete_original_backup_retained=verified_backup)
            elif name == 'write_fail':
                checks.update(failed_write_did_not_modify_device=readback == old,
                              original_backup_retained_before_write=verified_backup)
            elif wrote:
                checks['original_backup_retained_before_write'] = verified_backup
            passed = all(checks.values())
            report['cases'].append({'name': name, 'pass': passed,
                'return_code': result.returncode, 'physical_write_attempted': wrote,
                'checks': checks, 'log_tail': log[-2000:]})
            print(json.dumps({'case': name, 'pass': passed, 'checks': checks}), flush=True)
        report['source_unchanged'] = a.installer.read_bytes() == source
        report['status'] = 'PASS_LOOPBACK_WRITER_AND_FAILURE_PROPAGATION' if (
            report['source_unchanged'] and all(c['pass'] for c in report['cases'])) else 'FAIL_WRITER_CASES'
    except Exception as e:
        report['status'] = 'HARNESS_ERROR_NOT_A_WRITER_PASS'
        report['error'] = type(e).__name__ + ': ' + str(e)
    finally:
        # Only resources returned by this process's losetup calls are detached.
        if mounted:
            subprocess.run([tools['umount'], '/data'], check=False)
        for device in reversed(loops):
            subprocess.run([tools['losetup'], '-d', device], check=False)
        report['fixture_root'] = str(root)
        report['test_script_sha256'] = sha(Path(__file__).read_bytes())
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'cases': len(report['cases']),
                      'failures': [c['name'] for c in report['cases'] if not c['pass']],
                      'report': str(a.output)}))
    return 0 if report['status'].startswith('PASS_') else 1

if __name__ == '__main__':
    sys.exit(main())
