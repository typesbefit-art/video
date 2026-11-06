import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(92);
Config.setOverwriteOutput(true);
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');
// Плёночное зерно плохо жмётся — даём кодеку больше битрейта.
Config.setCrf(18);

// Если Remotion не может скачать Chrome Headless Shell (офлайн, прокси),
// укажите путь к локальному Chromium: REMOTION_BROWSER=/path/to/chrome npm run render
if (process.env.REMOTION_BROWSER) {
  Config.setBrowserExecutable(process.env.REMOTION_BROWSER);
}
