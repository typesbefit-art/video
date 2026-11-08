import {continueRender, delayRender, staticFile} from 'remotion';

// Local Rubik (OFL) with Cyrillic subset; avoids any network access while rendering.
const files: [string, string, string][] = [];
for (const w of ['500', '700', '800', '900']) {
  files.push([w, 'cyrillic', 'U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116']);
  files.push([w, 'latin', 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD']);
}

if (typeof document !== 'undefined') {
  const handle = delayRender('fonts');
  Promise.all(
    files.map(([w, sub, range]) => {
      const f = new FontFace('Rubik', `url(${staticFile(`fonts/rubik-${sub}-${w}-normal.woff2`)}) format('woff2')`, {weight: w, unicodeRange: range});
      document.fonts.add(f);
      return f.load();
    }),
  )
    .then(() => continueRender(handle))
    .catch((e) => {
      console.error('font load failed', e);
      continueRender(handle);
    });
}
