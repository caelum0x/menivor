/** TS≡Python parity — compiled TS caps/watermark/oauth must match the golden. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const here = dirname(fileURLToPath(import.meta.url));
const m = await import(join(here, "..", "dist", "index.js"));
const golden = JSON.parse(readFileSync(join(here, "fixtures", "golden", "connectors.json"), "utf8"));
function canon(v){if(Array.isArray(v))return `[${v.map(canon).join(",")}]`;if(v&&typeof v==="object")return `{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`;return JSON.stringify(v);}
let f=0,n=0; const ck=(l,g,w)=>{n++;if(canon(g)!==canon(w)){f++;console.error(`MISMATCH ${l}\n TS ${canon(g)}\n PY ${canon(w)}`);}};
ck("caps", m.CAPS, golden.caps);
ck("oauth", m.OAUTH, golden.oauth);
for(const [nm,c] of Object.entries(golden.validate)){const [p,d,a,cap,fmt]=c.args; ck(`validate.${nm}`, m.validatePublish(p,{duration_s:d,aspect:a,caption_len:cap,fmt}), c.errors);}
for(const [nm,exp] of Object.entries(golden.watermark)){const [t,w]=nm.split("<-"); ck(`wm.${nm}`, m.checkWatermark(t, w==="none"?"":w), exp);}
ck("remaining.10", m.remainingDaily("tiktok",10), golden.remaining.tiktok_10);
ck("remaining.20", m.remainingDaily("tiktok",20), golden.remaining.tiktok_20);
for(const [p,exp] of Object.entries(golden.oauth_derived)) ck(`oauth.${p}`, {scope_string:m.scopeString(p),pkce:m.requiresPkce(p)}, exp);
if(f){console.error(`\npublishing-connectors parity FAILED: ${f}/${n}`);process.exit(1);}
console.log(`publishing-connectors TS≡Python parity OK (${n} cases)`);
