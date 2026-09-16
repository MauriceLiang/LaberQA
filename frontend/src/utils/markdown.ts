export type MarkdownInlineToken =
  | { type: 'text'; text: string }
  | { type: 'strong'; text: string }
  | { type: 'emphasis'; text: string }
  | { type: 'code'; text: string }
  | { type: 'line-break' }

export type MarkdownBlock =
  | { type: 'paragraph'; tokens: MarkdownInlineToken[] }
  | { type: 'heading'; level: number; tokens: MarkdownInlineToken[] }
  | { type: 'unordered-list'; items: MarkdownInlineToken[][] }
  | { type: 'ordered-list'; items: MarkdownInlineToken[][] }
  | { type: 'quote'; tokens: MarkdownInlineToken[] }
  | { type: 'code'; code: string }

const inlineMarkers = [
  { close: '**', open: '**', type: 'strong' as const },
  { close: '__', open: '__', type: 'strong' as const },
  { close: '`', open: '`', type: 'code' as const },
  { close: '*', open: '*', type: 'emphasis' as const },
  { close: '_', open: '_', type: 'emphasis' as const },
]

function isEscapableCharacter(value: string) {
  return '*_`\\'.includes(value)
}

export function parseInlineMarkdown(value: string): MarkdownInlineToken[] {
  const tokens: MarkdownInlineToken[] = []
  let plainText = ''

  const flushPlainText = () => {
    if (!plainText) return
    tokens.push({ type: 'text', text: plainText })
    plainText = ''
  }

  let index = 0
  while (index < value.length) {
    const character = value[index]

    if (character === '\n') {
      flushPlainText()
      tokens.push({ type: 'line-break' })
      index += 1
      continue
    }

    if (character === '\\' && isEscapableCharacter(value[index + 1] ?? '')) {
      plainText += value[index + 1]
      index += 2
      continue
    }

    const marker = inlineMarkers.find(({ open }) => value.startsWith(open, index))
    if (!marker) {
      plainText += character
      index += 1
      continue
    }

    const contentStart = index + marker.open.length
    const contentEnd = value.indexOf(marker.close, contentStart)
    if (contentEnd <= contentStart || /^\s|\s$/.test(value.slice(contentStart, contentEnd))) {
      plainText += marker.open
      index += marker.open.length
      continue
    }

    flushPlainText()
    tokens.push({ type: marker.type, text: value.slice(contentStart, contentEnd) })
    index = contentEnd + marker.close.length
  }

  flushPlainText()
  return tokens
}

type ListKind = 'unordered-list' | 'ordered-list'

function listMatch(line: string): { kind: ListKind; content: string } | null {
  const unordered = line.match(/^\s*[-*+•–—]\s+(.+)$/)
  if (unordered) return { kind: 'unordered-list', content: unordered[1] }

  const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/)
  if (ordered) return { kind: 'ordered-list', content: ordered[1] }

  return null
}

export function parseMarkdown(source: string): MarkdownBlock[] {
  const lines = source.replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n')
  const blocks: MarkdownBlock[] = []
  let paragraphLines: string[] = []
  let listKind: ListKind | null = null
  let listItems: MarkdownInlineToken[][] = []
  let codeLines: string[] | null = null

  const flushParagraph = () => {
    if (!paragraphLines.length) return
    blocks.push({ type: 'paragraph', tokens: parseInlineMarkdown(paragraphLines.join('\n')) })
    paragraphLines = []
  }

  const flushList = () => {
    if (!listKind) return
    blocks.push({ type: listKind, items: listItems })
    listKind = null
    listItems = []
  }

  const flushTextBlocks = () => {
    flushParagraph()
    flushList()
  }

  for (const line of lines) {
    const fence = line.match(/^\s*```(?:\w+)?\s*$/)
    if (fence) {
      if (codeLines) {
        blocks.push({ type: 'code', code: codeLines.join('\n') })
        codeLines = null
      } else {
        flushTextBlocks()
        codeLines = []
      }
      continue
    }

    if (codeLines) {
      codeLines.push(line)
      continue
    }

    if (!line.trim()) {
      flushTextBlocks()
      continue
    }

    const heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/)
    if (heading) {
      flushTextBlocks()
      blocks.push({
        type: 'heading',
        level: heading[1].length,
        tokens: parseInlineMarkdown(heading[2]),
      })
      continue
    }

    const quote = line.match(/^\s*>\s?(.*)$/)
    if (quote) {
      flushTextBlocks()
      blocks.push({ type: 'quote', tokens: parseInlineMarkdown(quote[1]) })
      continue
    }

    const list = listMatch(line)
    if (list) {
      flushParagraph()
      if (listKind !== list.kind) {
        flushList()
        listKind = list.kind
      }
      listItems.push(parseInlineMarkdown(list.content))
      continue
    }

    flushList()
    paragraphLines.push(line)
  }

  if (codeLines) blocks.push({ type: 'code', code: codeLines.join('\n') })
  flushTextBlocks()
  return blocks
}
