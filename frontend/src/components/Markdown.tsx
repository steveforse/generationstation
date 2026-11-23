import { Fragment, type ReactNode } from 'react'

/**
 * Markdown from the chat model, drawn as React elements (never as HTML, so nothing in a reply can run).
 * Covers what models write: paragraphs, headings, lists (nested by indent), quotes, code blocks, tables,
 * rules, and inline code, bold, italic, strikethrough and links (http, https and mailto only).
 */
export function Markdown({ text }: { text: string }) {
  return <div className="markdown">{blocks(text.replace(/\r\n?/g, '\n').split('\n'))}</div>
}

const FENCE = /^\s*(```|~~~)\s*([\w+-]*)\s*$/
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/
const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

function blocks(lines: string[]): ReactNode[] {
  const out: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const key = out.length
    if (!line.trim()) { i++; continue }
    const fence = FENCE.exec(line)
    if (fence) {
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++])
      i++  // the closing fence (or the end, while the answer is still being written)
      out.push(<pre key={key} className="md-code">{fence[2] && <span className="md-code-lang">{fence[2]}</span>}<code>{body.join('\n')}</code></pre>)
      continue
    }
    const heading = HEADING.exec(line)
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6)  // h3 and below: the page already has h1 and h2
      const Tag = `h${level}` as 'h3'
      out.push(<Tag key={key} className="md-heading">{inline(heading[2])}</Tag>)
      i++
      continue
    }
    if (RULE.test(line)) { out.push(<hr key={key} />); i++; continue }
    if (line.trimStart().startsWith('>')) {
      const body: string[] = []
      while (i < lines.length && lines[i].trimStart().startsWith('>')) body.push(lines[i++].trimStart().replace(/^>\s?/, ''))
      out.push(<blockquote key={key}>{blocks(body)}</blockquote>)
      continue
    }
    if (line.includes('|') && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1])) {
      const header = cells(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]))
      out.push(<div key={key} className="md-table"><table><thead><tr>{header.map((cell, n) => <th key={n}>{inline(cell)}</th>)}</tr></thead>
        <tbody>{rows.map((row, r) => <tr key={r}>{header.map((_, n) => <td key={n}>{inline(row[n] ?? '')}</td>)}</tr>)}</tbody></table></div>)
      continue
    }
    if (ITEM.test(line)) {
      const body: string[] = []
      while (i < lines.length && (ITEM.test(lines[i]) || (lines[i].trim() && /^\s+/.test(lines[i])) || (!lines[i].trim() && i + 1 < lines.length && (ITEM.test(lines[i + 1]) || /^\s+\S/.test(lines[i + 1]))))) body.push(lines[i++])
      out.push(<Fragment key={key}>{list(body)}</Fragment>)
      continue
    }
    const paragraph: string[] = []
    while (i < lines.length && lines[i].trim() && !FENCE.test(lines[i]) && !HEADING.test(lines[i]) && !ITEM.test(lines[i]) && !lines[i].trimStart().startsWith('>') && !RULE.test(lines[i])) paragraph.push(lines[i++])
    if (paragraph.length === 0) { out.push(<p key={key}>{inline(lines[i++])}</p>); continue }
    out.push(<p key={key}>{paragraph.map((text, n) => <Fragment key={n}>{n > 0 && <br />}{inline(text.trim())}</Fragment>)}</p>)
  }
  return out
}

/** A list and the lists nested inside it (by indent). */
function list(lines: string[]): ReactNode {
  const first = ITEM.exec(lines[0])!
  const indent = first[1].length
  const ordered = /\d/.test(first[2])
  const items: { text: string; rest: string[] }[] = []
  for (const line of lines) {
    const match = ITEM.exec(line)
    if (match && match[1].length <= indent) items.push({ text: match[3], rest: [] })
    else if (items.length) items[items.length - 1].rest.push(line)
  }
  const start = ordered ? parseInt(first[2], 10) : undefined
  const children = items.map((item, n) => {
    const nested = item.rest.filter((line) => line.trim())
    const sub = nested.length ? (ITEM.test(nested[0]) ? list(nested) : blocks(nested.map((line) => line.trim()))) : null
    return <li key={n}>{inline(item.text)}{sub}</li>
  })
  return ordered ? <ol start={start !== 1 ? start : undefined}>{children}</ol> : <ul>{children}</ul>
}

function cells(line: string) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

const INLINE = /(`+)([\s\S]*?[^`])\1(?!`)|\*\*([\s\S]+?)\*\*|__([\s\S]+?)__|~~([\s\S]+?)~~|\*([^*\s][^*]*?)\*|(?<![\w])_([^_\s][^_]*?)_(?![\w])|\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0
    if (index > last) out.push(text.slice(last, index))
    const key = out.length
    if (match[1]) out.push(<code key={key}>{match[2].trim()}</code>)
    else if (match[3] ?? match[4]) out.push(<strong key={key}>{inline(match[3] ?? match[4])}</strong>)
    else if (match[5]) out.push(<del key={key}>{inline(match[5])}</del>)
    else if (match[6] ?? match[7]) out.push(<em key={key}>{inline(match[6] ?? match[7])}</em>)
    else if (match[8]) out.push(safeHref(match[9]) ? <a key={key} href={match[9]} target="_blank" rel="noreferrer noopener">{inline(match[8])}</a> : match[0])
    else if (match[10]) out.push(<a key={key} href={match[10]} target="_blank" rel="noreferrer noopener">{match[10]}</a>)
    last = index + match[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function safeHref(url: string) {
  return /^(https?:|mailto:)/i.test(url)
}
