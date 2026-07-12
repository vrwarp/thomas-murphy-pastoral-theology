// Typo-sweep validation pass. Candidates come from tools/find_typo_suspects.py
// (intra-corpus OCR-confusion frequency analysis); this workflow fans out one
// Sonnet/medium agent per suspect page to VALIDATE each candidate against the
// page image (the authority) and write confirmed fixes. Run with the Workflow
// tool inside Claude Code:
//   Workflow({ scriptPath: "tools/wf_validate_typos.js", args: {
//     pages: [5, 19, ...], hintsDir: "<repo>/work/typo-hints",
//     imgDir: "<repo>/work/ocr-images", outDir: "<repo>/work/typo-confirmed" }})
export const meta = {
  name: 'pastoral-theology-typo-validate',
  description: 'Validate OCR-typo suspects against page images (Sonnet/medium, 1 page per agent)',
  phases: [{ title: 'Validate', model: 'sonnet' }],
}

const A = (typeof args === 'string') ? JSON.parse(args) : args
const MODEL = 'sonnet', EFFORT = 'medium', ATYPE = 'general-purpose'

const STATUS = {
  type: 'object',
  properties: {
    page: { type: 'integer' }, wroteFile: { type: 'boolean' },
    nConfirmed: { type: 'integer' }, nRejected: { type: 'integer' }, note: { type: 'string' },
  },
  required: ['page', 'wroteFile', 'nConfirmed', 'nRejected'],
}

function pad(n) { return String(n).padStart(3, '0') }

function prompt(pg) {
  return [
    'This is a personal digitization project of a PUBLIC-DOMAIN book (Thomas Murphy, "Pastoral Theology", 1877; Internet Archive item pastoraltheology00murp). You are a PROOFREADER validating suspected OCR misreads against the printed page image. You output only small verdicts, never the page text.',
    '',
    'Read BOTH files with the Read tool:',
    '  1. Suspect list: ' + A.hintsDir + '/hints_p' + pad(pg) + '.json',
    '  2. Page image (the authority): ' + A.imgDir + '/p' + pad(pg) + '.png',
    '',
    'The suspect list gives, for each candidate: text_token (the word exactly as it stands in our transcription), suggested (the statistically likely correction), and context (surrounding words to help you locate it on the page).',
    '',
    'For EACH suspect: find that passage in the page image and read what the print actually says.',
    '- If the print shows the transcription is wrong, CONFIRM it: give the corrected word EXACTLY as printed (match its capitalization; e.g. names like McCheyne / M’Cheyne must be copied letter-for-letter from the image).',
    '- If the print actually reads the same as text_token (our transcription is right and merely unusual), REJECT it with a short reason.',
    '- If you cannot find or read the passage, REJECT it with reason "not found/illegible".',
    '',
    'Write your verdicts as a JSON object to EXACTLY this path with the Write tool:',
    '  ' + A.outDir + '/confirmed_p' + pad(pg) + '.json',
    'Format (nothing else in the file):',
    '{ "page": ' + pg + ',',
    '  "confirmed": [ {"wrong": "<text_token copied verbatim>", "right": "<word as printed>"} ],',
    '  "rejected":  [ {"wrong": "<text_token>", "reason": "<short>"} ] }',
    '',
    'Then return the status (page=' + pg + ', wroteFile=true, nConfirmed, nRejected).',
  ].join('\n')
}

const statuses = await parallel(A.pages.map(pg => () =>
  agent(prompt(pg), { label: 'p' + pad(pg), phase: 'Validate',
    model: MODEL, effort: EFFORT, agentType: ATYPE, schema: STATUS })
    .then(s => s || { page: pg, wroteFile: false, nConfirmed: 0, nRejected: 0 })))

const ok = statuses.filter(s => s && s.wroteFile)
const failed = A.pages.filter((p, i) => !(statuses[i] && statuses[i].wroteFile))
const confirmed = ok.reduce((n, s) => n + (s.nConfirmed || 0), 0)
const rejected = ok.reduce((n, s) => n + (s.nRejected || 0), 0)
log('validated ' + ok.length + '/' + A.pages.length + ' pages | confirmed ' + confirmed + ' | rejected ' + rejected)
return { ok: ok.length, total: A.pages.length, confirmed, rejected, failed }
