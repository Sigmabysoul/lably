export type LabelStatus = 'processing' | 'processed' | 'review' | 'failed'
export type ProcessingMode = 'amazon' | 'flipkart'

export type FlipkartLabel = {
  id: string
  pageIndex: number
  half: 'top' | 'bottom'
  consignmentId: string
  boxId: string
  labelNumber: string
  status: LabelStatus
  message?: string
}

export type LabelRecord = {
  id: string
  file: File
  fileName: string
  orderNumber: string
  productCode: string
  candidates: string[]
  status: LabelStatus
  message?: string
  originalUrl?: string
}

export function extractFlipkartLabels(text: string, pageIndex: number) {
  const consignmentMatches = [...text.matchAll(/\bfk_[a-z0-9]+_\d+\b/gi)].map((match) => match[0])
  const boxMatches = [...text.matchAll(/\bfk_[a-z0-9]+_\d+_\d+\b/gi)].map((match) => match[0])
  const labelMatches = [...text.matchAll(/\[\s*(\d+)\s+of\s+(\d+)\s*\]/gi)].map((match) => `[${match[1]} of ${match[2]}]`)
  const uniqueConsignments = [...new Set(consignmentMatches)]
  const uniqueBoxes = [...new Set(boxMatches)]
  return (['top', 'bottom'] as const).map((half, index) => {
    const boxId = uniqueBoxes[index] ?? ''
    const consignmentId = uniqueConsignments.find((value) => boxId.startsWith(`${value}_`)) ?? uniqueConsignments[index] ?? ''
    return { id: `flipkart-${pageIndex}-${half}`, pageIndex, half, consignmentId, boxId, labelNumber: labelMatches[index] ?? '', status: boxId && consignmentId ? 'processed' as const : 'review' as const, message: boxId && consignmentId ? undefined : 'Could not confidently extract both IDs. Enter them manually.' }
  })
}

export function extractOrderNumber(text: string) {
  const matches = text.match(/\b\d{3}-\d{7}-\d{7}\b/g)
  return matches?.[0] ?? ''
}

export function extractProductCandidates(text: string) {
  const candidates = [...text.matchAll(/\(\s*([A-Za-z0-9][A-Za-z0-9_-]{2,})\s*\)/g)]
    .map((match) => match[1].trim())
    .filter((value, index, all) => all.indexOf(value) === index)
    .sort((a, b) => scoreSku(b) - scoreSku(a))
  return candidates
}

function scoreSku(value: string) {
  return (/[A-Z]/i.test(value) ? 2 : 0) + (/\d/.test(value) ? 2 : 0) + (/[_-]/.test(value) ? 3 : 0) + Math.min(value.length / 20, 1)
}

export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
