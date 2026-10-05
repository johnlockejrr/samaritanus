// Marks matching words as React nodes. Verse text is never parsed as HTML.
const HL_OPEN = "<hl>";
const HL_CLOSE = "</hl>";

const FINALS = {
  "\u05da": "\u05db",
  "\u05dd": "\u05de",
  "\u05df": "\u05e0",
  "\u05e3": "\u05e4",
  "\u05e5": "\u05e6",
};

export function consonantal(value) {
  // NFKD + strip marks so vocalized / cantillated paste matches the index.
  const stripped = String(value ?? "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "");
  let out = "";
  for (const ch of stripped) {
    if (ch >= "\u05d0" && ch <= "\u05ea") out += FINALS[ch] || ch;
  }
  return out;
}

export function parseHighlight(marked, plain) {
  const source = marked ?? plain ?? "";
  if (!source.includes(HL_OPEN)) return [{ text: source, hit: false }];
  const out = [];
  let rest = source;
  while (rest.length) {
    const open = rest.indexOf(HL_OPEN);
    if (open === -1) {
      out.push({ text: rest, hit: false });
      break;
    }
    if (open > 0) out.push({ text: rest.slice(0, open), hit: false });
    rest = rest.slice(open + HL_OPEN.length);
    const close = rest.indexOf(HL_CLOSE);
    if (close === -1) {
      out.push({ text: rest, hit: true });
      break;
    }
    out.push({ text: rest.slice(0, close), hit: true });
    rest = rest.slice(close + HL_CLOSE.length);
  }
  return out;
}

export function markTokens(plain, matches) {
  const source = plain ?? "";
  const norms = new Set((matches || []).map(consonantal).filter(Boolean));
  if (!norms.size) return [{ text: source, hit: false }];
  return source.split(/(\s+)/).map((part) => ({
    text: part,
    hit: norms.has(consonantal(part)),
  }));
}

export default function Highlight({ marked, plain, matches, className = "" }) {
  const parts = matches
    ? markTokens(plain ?? "", matches)
    : parseHighlight(marked, plain);
  return (
    <span className={className}>
      {parts.map((part, i) =>
        part.hit ? (
          <strong key={i} className="font-bold">
            {part.text}
          </strong>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </span>
  );
}
