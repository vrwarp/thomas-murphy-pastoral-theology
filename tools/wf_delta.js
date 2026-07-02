// Step 2 (AI proofreading) of the pipeline. This is a Claude Code *Workflow* script: it
// fans out one Sonnet/medium agent per page. Each agent reads the page image + OCR text and
// writes a small delta JSON {drop, fixes, headings, italics} to outDir. It must be run with
// the Workflow tool inside Claude Code (not plain `node`). Example invocation (args as JSON):
//   Workflow({ scriptPath: "tools/wf_delta.js", args: {
//     ocrDir: "<repo>/artifacts/ocr", imgDir: "<repo>/work/ocr-images",
//     outDir: "<repo>/artifacts/deltas",
//     preface: [4,5,6,7], body: {start:14,end:501}, index:{start:502,end:510},
//     openers: { "38":{num:"II",title:"..."}, ... },   // chapter-opener pages, to drop banners
//     only: [ ...pages... ]                              // optional: re-run just these pages
//   }})
// The produced deltas are checked into artifacts/deltas/, so this step can be SKIPPED when
// rebuilding the EPUB from the saved artifacts.
export const meta = {
  name: 'pastoral-theology-delta',
  description: 'Per-page Sonnet/medium proofreading deltas (fixes/headings/italics/drops) vs the page image for a public-domain 1877 book',
  phases: [
    { title: 'Preface', model: 'sonnet' },
    { title: 'Body', model: 'sonnet' },
    { title: 'Index', model: 'sonnet' },
  ],
}

const A = (typeof args === 'string') ? JSON.parse(args) : args
if (!A || !A.ocrDir) { log('ERROR: args missing: ' + JSON.stringify(args).slice(0, 200)) }
const OCR = A.ocrDir, IMG = A.imgDir, OUT = A.outDir
const MODEL = 'sonnet', EFFORT = 'medium', ATYPE = 'general-purpose'
const only = A.only ? new Set(A.only) : null

const STATUS = {
  type: 'object',
  properties: {
    page: { type: 'integer' }, wroteFile: { type: 'boolean' },
    nFixes: { type: 'integer' }, nHeadings: { type: 'integer' }, note: { type: 'string' },
  },
  required: ['page', 'wroteFile'],
}

function pad(n) { return String(n).padStart(3, '0') }
const txt = p => OCR + '/p' + pad(p) + '.txt'
const img = p => IMG + '/p' + pad(p) + '.png'
const outj = p => OUT + '/delta_p' + pad(p) + '.json'

const PROV = 'This is a personal digitization project of a PUBLIC-DOMAIN book (Thomas Murphy, "Pastoral Theology", 1877; author 1823-1900; Internet Archive item pastoraltheology00murp). You are a PROOFREADER: you compare raw OCR text to the page image and output only a small list of corrections and formatting notes. You do NOT reproduce the page text.'

const SCHEMA_DOC = [
  'Output ONLY a compact JSON object (no page prose). Schema:',
  '{',
  '  "drop": [ "<exact text of a line to delete: the running head, and the page number>" ],',
  '  "fixes": [ {"wrong":"<short exact OCR substring that is wrong>", "right":"<corrected substring>"} ],',
  '  "headings": [ {"text":"<full corrected text of a centered small-caps heading, in reading order>", "level":"h2"} ],',
  '  "italics": [ "<a word or short phrase that is printed in italics in the body text>" ]',
  '}',
  'Guidance:',
  '- "drop": the top running head line (a short italic title) and the page-number token. Include each exactly as it appears in the OCR text so it can be matched and removed.',
  '- "fixes": ONLY real OCR errors you can confirm against the image (wrong letters, wrong punctuation, split/merged words, e.g. "Tuat"->"That", "effliciency"->"efficiency", "{d)"->"(d)"). Keep each snippet short and unique enough to find. Do not list correct text.',
  '- "headings": every centered heading printed in small capitals. Give its FULL correct text (fix OCR errors in it). Use level "h3" if it begins with a parenthesized letter like "(a)"; otherwise "h2". List in top-to-bottom order.',
  '- "italics": distinct words/short phrases shown in italics within body text (NOT the running head). Often none — then use an empty list.',
  'If a category has nothing, use an empty array. Keep the JSON small.',
].join('\n')

function base(p, roleLines) {
  return [
    PROV, '',
    'Page image (the authority): ' + img(p),
    'Raw OCR text: ' + txt(p), '',
    'Read BOTH files with the Read tool. Then compare.', '',
    roleLines, '',
    SCHEMA_DOC, '',
    'Write the JSON object to EXACTLY: ' + outj(p) + '  (use the Write tool; write only the JSON).',
    'Then return the status (page=' + p + ', wroteFile=true, nFixes, nHeadings).',
  ].join('\n')
}

function bodyPrompt(t) {
  const lines = []
  if (t.opener) {
    lines.push('NOTE: this page BEGINS Chapter ' + t.opener.num + ' ("' + t.opener.title + '"). Add to "drop" the big "PASTORAL THEOLOGY" banner line (if present), the "CHAPTER ' + t.opener.num + '." line, and the chapter-title line — these are re-added elsewhere and must be removed. Do NOT list them as headings.')
  }
  lines.push('This is a normal body page.')
  return base(t.page, lines.join('\n'))
}
function prefacePrompt(t) {
  return base(t.page, 'This is a PREFACE page. Add the running head "PREFACE." and the page number to "drop". Do not list "Preface" as a heading.')
}
function indexPrompt(t) {
  return base(t.page, 'This is a two-column alphabetical INDEX page. Add the running head "INDEX." and the page number to "drop". For "headings", list any centered single capital letter divider (e.g. "R") with level "h2". Only give "fixes" for clear OCR errors. Ignore italics.')
}

const tasks = []
if (A.preface) for (const p of A.preface) tasks.push({ page: p, kind: 'preface', phase: 'Preface' })
if (A.body) {
  const op = A.openers || {}
  for (let p = A.body.start; p <= A.body.end; p++)
    tasks.push({ page: p, kind: 'body', phase: 'Body', opener: op[String(p)] || null })
}
if (A.index) for (let p = A.index.start; p <= A.index.end; p++) tasks.push({ page: p, kind: 'index', phase: 'Index' })
const active = only ? tasks.filter(t => only.has(t.page)) : tasks
log('Proofreading ' + active.length + ' pages (1 agent per page)')

function promptFor(t) {
  if (t.kind === 'preface') return prefacePrompt(t)
  if (t.kind === 'index') return indexPrompt(t)
  return bodyPrompt(t)
}

const statuses = await parallel(active.map(t => () =>
  agent(promptFor(t), { label: 'p' + pad(t.page), phase: t.phase,
    model: MODEL, effort: EFFORT, agentType: ATYPE, schema: STATUS })
    .then(s => s || { page: t.page, wroteFile: false })))

const ok = statuses.filter(s => s && s.wroteFile).length
const failed = active.filter((t, i) => !(statuses[i] && statuses[i].wroteFile)).map(t => t.page)
log('Deltas written: ' + ok + '/' + active.length + '. Failed: ' + JSON.stringify(failed))
return { ok, total: active.length, failed }
