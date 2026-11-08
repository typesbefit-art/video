"""CLI: parallel deterministic render piped straight into ffmpeg (no PNGs)."""
import argparse
import json
import multiprocessing as mp
import os
import subprocess
import sys
import tempfile
import time

from .config import Settings

_G = {}


def _init_worker():
    from .renderer import Renderer
    _G['R'] = Renderer(_G['S'], scene=_G['scene'], choreo=_G['choreo'])


def _render_chunk(args):
    i0, i1 = args
    R, S = _G['R'], _G['S']
    out = []
    for i in range(i0, i1):
        t = S.t_start + i / S.fps
        gframe = int(round(t * 120))  # grain / noise keyed to master timeline
        out.append(R.render(t, gframe).tobytes())
    return i0, b''.join(out)


def _bar(done, total, t0):
    el = time.time() - t0
    rate = done / el if el > 0 else 0
    eta = (total - done) / rate if rate > 0 else 0
    w = 34
    f = int(w * done / total)
    sys.stderr.write('\r[%s%s] %d/%d  %.1f fps  elapsed %ds  ETA %ds ' %
                     ('#' * f, '.' * (w - f), done, total, rate, el, eta))
    sys.stderr.flush()


def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_entries',
                        'stream=codec_type,codec_name,profile,width,height,r_frame_rate,nb_read_frames,'
                        'pix_fmt,sample_rate,channels,bit_rate:format=duration',
                        '-of', 'json', path], capture_output=True, text=True)
    return json.loads(r.stdout)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Render the procedural TikTok fight video.')
    ap.add_argument('--preview', action='store_true', help='540x960, 30 fps, first 3 s')
    ap.add_argument('--debug-safe-zones', action='store_true', help='overlay TikTok UI safe zones')
    ap.add_argument('--out', default=None)
    ap.add_argument('--width', type=int, default=None)
    ap.add_argument('--height', type=int, default=None)
    ap.add_argument('--fps', type=int, default=None)
    ap.add_argument('--start', type=float, default=None)
    ap.add_argument('--end', type=float, default=None)
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument('--chunk', type=int, default=4, help='frames per worker task')
    ap.add_argument('--crf', type=int, default=18)
    ap.add_argument('--preset', default='medium')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--mb-samples', type=int, default=None, help='motion-blur sub-samples (default 4)')
    ap.add_argument('--no-60fps', action='store_true', help='skip the extra 60 fps export')
    a = ap.parse_args(argv)

    S = Settings()
    if a.preview:
        S.width, S.height, S.fps, S.t_end = 540, 960, 30, 3.0
    if a.width:
        S.width = a.width
    if a.height:
        S.height = a.height
    if a.fps:
        S.fps = a.fps
    if a.start is not None:
        S.t_start = a.start
    if a.end is not None:
        S.t_end = a.end
    if a.seed is not None:
        S.seed = a.seed
    if a.mb_samples is not None:
        S.mb_samples = a.mb_samples
    S.debug_safe_zones = a.debug_safe_zones
    out = a.out or ('fight_preview.mp4' if a.preview else 'fight_tiktok.mp4')
    N = S.n_frames
    print('Rendering %s: %dx%d @ %d fps, %.2f-%.2f s, %d frames, %d workers' %
          (out, S.width, S.height, S.fps, S.t_start, S.t_end, N, a.workers))

    t0 = time.time()
    from .scene import Scene
    from .choreography import Choreo
    from .audio import build_audio, write_wav, SR
    _G['S'] = S
    _G['scene'] = Scene(S.seed)
    _G['choreo'] = Choreo()
    print('scene + choreography + spring sim: %.1fs' % (time.time() - t0))

    t1 = time.time()
    audio, L, tp = build_audio(S.seed)
    i0, i1 = int(round(S.t_start * SR)), int(round(S.t_end * SR))
    tmpd = tempfile.mkdtemp(prefix='fight_')
    wav = os.path.join(tmpd, 'audio.wav')
    write_wav(wav, audio[i0:i1])
    print('audio: %.2f LUFS (full mix), true peak %.2f dBTP, %.1fs' % (L, 20 * __import__('math').log10(tp), time.time() - t1))

    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
           '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (S.width, S.height), '-r', str(S.fps),
           '-i', '-', '-i', wav,
           '-map', '0:v', '-map', '1:a',
           '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-crf', str(a.crf),
           '-preset', a.preset, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
           '-movflags', '+faststart', '-t', '%.6f' % (N / S.fps), out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    chunks = [(i, min(i + a.chunk, N)) for i in range(0, N, a.chunk)]
    t2 = time.time()
    done = 0
    if a.workers <= 1:
        _init_worker()
        for c in chunks:
            _, data = _render_chunk(c)
            ff.stdin.write(data)
            done += c[1] - c[0]
            _bar(done, N, t2)
    else:
        ctx = mp.get_context('fork')  # workers inherit the pre-built scene copy-on-write
        with ctx.Pool(a.workers, initializer=_init_worker) as pool:
            pending = {}
            nxt = 0
            it = iter(chunks)
            inflight = []
            limit = a.workers * 3  # back-pressure: bounded RAM
            for c in it:
                inflight.append(pool.apply_async(_render_chunk, (c,)))
                if len(inflight) >= limit:
                    break
            for c in it:
                r = inflight.pop(0).get()
                ff.stdin.write(r[1])
                done += len(r[1]) // (S.width * S.height * 3)
                _bar(done, N, t2)
                inflight.append(pool.apply_async(_render_chunk, (c,)))
            for r in inflight:
                r = r.get()
                ff.stdin.write(r[1])
                done += len(r[1]) // (S.width * S.height * 3)
                _bar(done, N, t2)
    ff.stdin.close()
    ff.wait()
    sys.stderr.write('\n')
    print('render+encode: %.1fs (%.2f s/frame/worker)' % (time.time() - t2, (time.time() - t2) * a.workers / N))
    if ff.returncode != 0:
        raise SystemExit('ffmpeg failed')

    outs = [out]
    if not a.no_60fps and not a.preview and S.fps > 60:
        o60 = out.replace('.mp4', '_60fps.mp4')
        subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', out, '-vf', 'fps=60',
                        '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-crf', str(a.crf),
                        '-preset', a.preset, '-c:a', 'copy', '-movflags', '+faststart', o60], check=True)
        outs.append(o60)
    for o in outs:
        info = probe(o)
        print('--', o)
        for s in info['streams']:
            if s['codec_type'] == 'video':
                print('   video: %s %s %dx%d %s fps, %s frames, %s' % (s['codec_name'], s.get('profile'), s['width'],
                      s['height'], s['r_frame_rate'], s.get('nb_read_frames'), s['pix_fmt']))
            else:
                print('   audio: %s %s Hz %sch %s bps' % (s['codec_name'], s['sample_rate'], s['channels'], s.get('bit_rate')))
        print('   duration: %s s' % info['format']['duration'])
    os.remove(wav)
    os.rmdir(tmpd)
    print('total %.1fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
