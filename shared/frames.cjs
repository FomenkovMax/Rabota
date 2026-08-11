/* Cuts a generated clip into the numbered JPEG sequence the engine scrubs.
   usage: node shared/frames.cjs <video> <outDir> <targetCount> [width] [quality] [crop]
   crop is ffmpeg's W:H:X:Y — generated clips sometimes carry a baked-in
   border, and scrubbing a letterboxed frame full-bleed looks broken.

   The clip's own frame rate is irrelevant to the page — what matters is
   landing close to targetCount evenly spaced frames, because the engine maps
   scroll position straight onto the frame index. */
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

let ffmpeg;
try {
  ffmpeg = require('ffmpeg-static');
} catch {
  console.error('ffmpeg-static is missing — run: npm i ffmpeg-static');
  process.exit(1);
}
const ffprobe = ffmpeg.replace(/ffmpeg$/, 'ffprobe');

const [, , video, outDir, countArg, widthArg, qArg, cropArg] = process.argv;
const target = Number(countArg || 71);
const width = Number(widthArg || 1280);
const quality = Number(qArg || 5); // ffmpeg -q:v, 2 = best, 31 = worst

fs.mkdirSync(outDir, { recursive: true });
for (const f of fs.readdirSync(outDir)) if (f.endsWith('.jpg')) fs.unlinkSync(path.join(outDir, f));

let duration = 5;
try {
  duration = Number(execFileSync(ffprobe, [
    '-v', 'error', '-show_entries', 'format=duration',
    '-of', 'default=noprint_wrappers=1:nokey=1', video
  ]).toString().trim()) || 5;
} catch { /* ffprobe is optional; the 5s default matches what we generate */ }

const fps = target / duration;
const crop = cropArg ? `crop=${cropArg},` : '';
execFileSync(ffmpeg, [
  '-v', 'error', '-i', video,
  '-vf', `fps=${fps.toFixed(4)},${crop}scale=${width}:-2:flags=lanczos`,
  '-q:v', String(quality),
  '-frames:v', String(target),
  path.join(outDir, '%03d.jpg')
]);

const files = fs.readdirSync(outDir).filter(f => f.endsWith('.jpg')).sort();
const bytes = files.reduce((n, f) => n + fs.statSync(path.join(outDir, f)).size, 0);
console.log(`${outDir}: ${files.length} frames, ${(bytes / 1048576).toFixed(2)} MB, ` +
            `${(bytes / files.length / 1024).toFixed(0)} KB avg (source ${duration.toFixed(2)}s)`);
