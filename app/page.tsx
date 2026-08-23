// Frontend UI component - runs client-side in Next.js
'use client'

// Import React hooks
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Boxes,
  Download,
  FileCheck2,
  FileText,
  FolderOpen,
  PackageCheck,
  Plus,
  RotateCcw,
  ScanLine,
  Settings2,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  downloadBlob,
  extractFlipkartLabels,
  extractOrderNumber,
  extractProductCandidates,
  type FlipkartLabel,
  type LabelStatus,
  type ProcessingMode,
} from '@/lib/label-processing'

// Generate a unique ID
function createId(): string {
  // Use the browser crypto API when available
  if (
    typeof window !== 'undefined' &&
    window.crypto &&
    typeof window.crypto.randomUUID === 'function'
  ) {
    return window.crypto.randomUUID()  // Generate a proper UUID
  }
  // Fallback: combine a timestamp and random string
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
}

// Backend API base URL (from the environment or the default)
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// Demo data - loaded when the app starts for the first time

interface FlipkartPanelProps {
  labels: FlipkartLabel[]
  selected?: FlipkartLabel
  manualConsignment: string
  manualBox: string
  setManualConsignment: (val: string) => void
  setManualBox: (val: string) => void
  onManual: () => void
  previewMode: 'original' | 'modified'
  setPreviewMode: (mode: 'original' | 'modified') => void
  onDownload: () => void
  isProcessing: boolean
}

interface AmazonPanelProps {
  rows: AmazonQueueRow[]
  selected?: AmazonQueueRow
  selectedId: string
  setSelectedId: (id: string) => void
  onDownload: () => void
  onDownloadAll: () => void
  isProcessing: boolean
}

interface AmazonItem {
  productCode: string
  quantity: string
}

interface AmazonQueueRow {
  id: string
  file: File
  fileName: string
  orderNumber: string
  productCode: string
  candidates: string[]
  status: LabelStatus
  originalUrl?: string
  message?: string
  amazonItems: AmazonItem[]
}

export default function Page() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<ProcessingMode>('amazon')
  const [rows, setRows] = useState<AmazonQueueRow[]>([])
  const [flipkartRows, setFlipkartRows] = useState<FlipkartLabel[]>([])
  const [flipkartFile, setFlipkartFile] = useState<File | null>(null)
  const [selectedId, setSelectedId] = useState('demo-1')
  const [previewMode, setPreviewMode] = useState<'original' | 'modified'>('modified')
  const [manualConsignment, setManualConsignment] = useState('')
  const [manualBox, setManualBox] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)

  const selected = rows.find((row) => row.id === selectedId) ?? rows[0]
  const selectedFlipkart = flipkartRows[0]

  // Cleanup object URLs cleanly to avoid memory leaks
  useEffect(() => {
    return () => {
      rows.forEach((row) => {
        if (row.originalUrl) URL.revokeObjectURL(row.originalUrl)
      })
    }
  }, [rows])

  const stats = useMemo(
    () => ({
      total: mode === 'flipkart' ? flipkartRows.length : rows.length,
      processed:
        mode === 'flipkart'
          ? flipkartRows.filter((row) => row.status === 'processed').length
          : rows.filter((row) => row.status === 'processed').length,
      review:
        mode === 'flipkart'
          ? flipkartRows.filter((row) => row.status === 'review').length
          : rows.filter((row) => row.status === 'review').length,
      failed: rows.filter((row) => row.status === 'failed').length,
    }),
    [mode, rows, flipkartRows]
  )

  const statCards: Array<{ label: string; value: number; Icon: LucideIcon }> = [
    { label: 'Labels', value: stats.total, Icon: FileText },
    { label: 'Processed', value: stats.processed, Icon: FileCheck2 },
    { label: 'Needs review', value: stats.review, Icon: RotateCcw },
    { label: 'Failed', value: stats.failed, Icon: X },
  ]

  // Read and parse the Amazon PDF pair by pair.
  // Each shipping page and invoice page pair gets an independent UI row.
  async function readAmazon(file: File): Promise<AmazonQueueRow[]> {
    try {
      const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
      pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

      const pdf = await pdfjs.getDocument({
        data: new Uint8Array(await file.arrayBuffer()),
      }).promise

      // The backend also processes Amazon PDFs in two-page pairs:
      // shipping label (odd page) + invoice label (even page).
      const pageTexts: string[] = []
      for (let i = 0; i < pdf.numPages; i++) {
        const page = await pdf.getPage(i + 1)
        const content = await page.getTextContent()
        pageTexts.push(
          content.items
            .map((item) => ('str' in item ? item.str : ''))
            .join(' ')
            .replace(/\s+/g, ' ')
            .trim(),
        )
      }

      function extractAmazonItem(text: string): AmazonItem {
        if (!text) return { productCode: 'UNKNOWN-SKU', quantity: '1' }

        let foundSku: string | null = null
        let foundQty: string | null = null

        // Same extraction priority as services/amazon.py.
        const bracketHsnMatch = text.match(
          /\(\s*([A-Za-z0-9_\-\.\/]+?)\s*\)\s*(?:\n|\s)*HSN/i,
        )
        if (bracketHsnMatch) foundSku = bracketHsnMatch[1].trim()

        if (!foundSku) {
          const bracketMatches = text.match(/\(\s*([A-Za-z0-9]*[_\-][A-Za-z0-9_\-\.]+)\s*\)/g)
          if (bracketMatches) {
            for (const match of bracketMatches) {
              const candidate = match.replace(/[()]/g, '').trim()
              if (!candidate.toLowerCase().startsWith('page') && candidate.length > 3) {
                foundSku = candidate
                break
              }
            }
          }
        }

        if (!foundSku) {
          const hsnMatch = text.match(/([A-Za-z0-9_\-\.]{3,50})\s*(?:\n|\s)*HSN/i)
          if (hsnMatch) foundSku = hsnMatch[1].trim()
        }

        if (!foundSku) {
          const asinMatch = text.match(/\b(B0[A-Z0-9]{8})\b/)
          if (asinMatch) foundSku = asinMatch[1].trim()
        }

        const qtyMatch = text.match(/(?:Qty|Quantity)\s*[:\-]?\s*(\d+)/i)
        if (qtyMatch) {
          foundQty = qtyMatch[1].trim()
        } else {
          const tableQtyMatch = text.match(/(?:₹[\d\.,]+\s+)(\d{1,3})(?:\s+₹[\d\.,]+)/)
          if (tableQtyMatch) foundQty = tableQtyMatch[1].trim()
        }

        return {
          productCode: foundSku || 'UNKNOWN-SKU',
          quantity: foundQty || '1',
        }
      }

      const items: AmazonItem[] = []
      for (let i = 0; i < pageTexts.length; i += 2) {
        const invoiceText = pageTexts[i + 1] || pageTexts[i] || ''
        items.push(extractAmazonItem(invoiceText))
      }

      const fileUrl = URL.createObjectURL(file)
      const orderNumber = extractOrderNumber(file.name) || 'N/A'
      const rowsForFile: AmazonQueueRow[] = items.map((item, index) => ({
        id: createId(),
        file,
        fileName: `${file.name} · Pair ${index + 1}`,
        orderNumber,
        productCode: item.productCode,
        candidates: [item.productCode],
        status: 'processed',
        originalUrl: fileUrl,
        amazonItems: [item],
      }))

      if (!rowsForFile.length) {
        rowsForFile.push({
          id: createId(),
          file,
          fileName: file.name,
          orderNumber,
          productCode: '',
          candidates: [],
          status: 'failed',
          message: 'Could not read this PDF.',
          originalUrl: fileUrl,
          amazonItems: [],
        })
      }

      return rowsForFile
    } catch (err) {
      console.error('Failed reading Amazon label:', err)
      return [
        {
          id: createId(),
          file,
          fileName: file.name,
          orderNumber: '',
          productCode: '',
          candidates: [],
          status: 'failed',
          message: 'Could not read this PDF.',
          amazonItems: [],
        },
      ]
    }
  }

  // Read and parse a Flipkart PDF file
  async function readFlipkart(
    file: File
  ): Promise<{ file: File; extracted: FlipkartLabel[] }> {
    try {
      // Load the PDF.js library dynamically
      const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
      // Set the worker script explicitly to avoid Next.js runtime issues
      pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

      // Load the PDF into memory from the file bytes
      const pdf = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise
      const extracted: FlipkartLabel[] = []  // Store extracted labels here
      
      // Process every page
      for (let pageIndex = 0; pageIndex < pdf.numPages; pageIndex++) {
        const page = await pdf.getPage(pageIndex + 1)  // Fetch the page by index
        const content = await page.getTextContent()  // Extract the page text
        const text = content.items.map((item) => ('str' in item ? item.str : '')).join(' ')  // Join the text
        extracted.push(...extractFlipkartLabels(text, pageIndex))  // Extract and add labels
      }
      return { file, extracted }
    } catch (err) {
      console.error('Failed parsing Flipkart PDF:', err)
      return {
        file,
        extracted: [
          {
            id: createId(),
            pageIndex: 0,
            half: 'top',
            consignmentId: '',
            boxId: '',
            labelNumber: '',
            status: 'review',
            message: 'Unable to parse PDF.',
          },
        ],
      }
    }
  }

  // Handle multiple PDF files
  async function handleFiles(files: FileList | File[]) {
    // Filter for PDF files only
    const pdfs = Array.from(files).filter(
      (file) => file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    )
    if (!pdfs.length) return  // Return when there are no PDFs
    setIsProcessing(true)  // Set the loading state

    try {
      if (mode === 'flipkart') {
        // Flipkart mode: parse all files
        const all: FlipkartLabel[] = []
        for (const file of pdfs) {
          const res = await readFlipkart(file)  // Parse each file
          all.push(...res.extracted)  // Collect extracted labels
        }
        setFlipkartFile(pdfs[0])  // Store the first file
        setFlipkartRows(all)  // Set all labels
      } else {
        // Amazon mode: parse each PDF and create a separate UI row for every two-page pair.
        const parsedFiles = await Promise.all(pdfs.map(readAmazon))
        const results = parsedFiles.flat()
        setRows(results)
        if (results.length > 0) {
          setSelectedId(results[0].id)  // Select the first result
        }
      }
    } catch (err) {
      console.error('Batch file handling error:', err)  // Log the error
    } finally {
      setIsProcessing(false)  // Clear the loading state
    }
  }

  // Drag-over handler - highlight the drop zone
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()  // Prevent the default behavior
    e.stopPropagation()  // Stop event propagation
  }

  // Drop handler - process the files
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()  // Prevent the default behavior
    e.stopPropagation()  // Stop event propagation
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files)  // Process the dropped files
    }
  }

  // Process a Flipkart PDF through the backend and download it
  async function downloadFlipkart() {
    if (!flipkartFile) return  // Return when there is no file
    setIsProcessing(true)  // Enable the processing state
    try {
      // Prepare form data for the API
      const formData = new FormData()
      formData.append('file', flipkartFile)  // Add the PDF file
      const boxId = manualBox || flipkartRows[0]?.boxId
      const consignmentId = manualConsignment || flipkartRows[0]?.consignmentId
      if (boxId) formData.append('box_id', boxId)  // Add the detected or manual Box ID
      if (consignmentId) formData.append('consignment_id', consignmentId)  // Add the detected or manual Consignment ID

      // Send a POST request to the backend API
      const response = await fetch(`${API_BASE_URL}/api/process-flipkart`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        let detail = ''
        try {
          const body = await response.json()
          detail = typeof body.detail === 'string' ? `: ${body.detail}` : ''
        } catch {
          // Keep the status when the server does not return JSON.
        }
        throw new Error(`Server returned ${response.status}${detail}`)
      }

      const blob = await response.blob()  // Convert the response to a blob
      downloadBlob(blob, `flipkart-modified-${flipkartFile.name}`)  // Download the result
    } catch (error) {
      console.error('Error processing Flipkart label:', error)  // Log the error
      alert(`Failed to process Flipkart label: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsProcessing(false)  // Disable the processing state
    }
  }

  // Process an Amazon PDF through the backend and download it
  async function downloadAmazon() {
    if (!selected || !selected.file || selected.file.size === 0) return  // Validate the selected file
    setIsProcessing(true)  // Enable the processing state
    try {
      // Prepare form data for the API
      const formData = new FormData()
      formData.append('file', selected.file)  // Add the PDF file
      if (selected.productCode) {
        formData.append('sku_code', selected.productCode)  // Add the product code/SKU
      }

      // Send a POST request to the backend API
      const response = await fetch(`${API_BASE_URL}/api/process-amazon`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) throw new Error(`Server returned ${response.status}`)  // Check for errors

      const blob = await response.blob()  // Convert the response to a blob
      downloadBlob(blob, `modified-${selected.file.name}`)  // Download the result
    } catch (error) {
      console.error('Error processing Amazon label:', error)  // Log the error
      alert('Failed to connect to processing backend. Check API endpoint.')  // Alert the user
    } finally {
      setIsProcessing(false)  // Disable the processing state
    }
  }
 
  // Batch download - process all Amazon PDFs and merge them into one PDF
  async function downloadAllAmazon() {
    if (rows.length === 0) return  // Return when there are no files
    setIsProcessing(true)  // Enable the processing state
    try {
      // Download the file directly when there is only one
      if (rows.length === 1) {
        await downloadAmazon()
        return
      }

      // Use pdf-lib to merge the PDFs
      const { PDFDocument } = await import('pdf-lib')
      const mergedPdf = await PDFDocument.create()  // Create a new PDF document

      // Process each unique physical PDF only once.
      const uniqueRows: AmazonQueueRow[] = []
      const seenFiles = new Set<File>()
      for (const row of rows) {
        if (seenFiles.has(row.file)) continue
        seenFiles.add(row.file)
        uniqueRows.push(row)
      }
      for (const row of uniqueRows) {
        try {
          const formData = new FormData()
          formData.append('file', row.file)  // Add the PDF file
          if (row.productCode) {
            formData.append('sku_code', row.productCode)  // Add the product code/SKU
          }

          // Send a POST request to the backend API
          const response = await fetch(`${API_BASE_URL}/api/process-amazon`, {
            method: 'POST',
            body: formData,
          })

          if (response.ok) {
            const blob = await response.blob()  // Convert the response to a blob
            const arrayBuffer = await blob.arrayBuffer()  // Convert the blob to an ArrayBuffer
            const pdf = await PDFDocument.load(arrayBuffer)  // Load the PDF
            const copiedPages = await mergedPdf.copyPages(pdf, pdf.getPageIndices())  // Copy the pages
            copiedPages.forEach((page) => mergedPdf.addPage(page))  // Add pages to the merged PDF
          }
        } catch (err) {
          console.error(`Error processing ${row.fileName}:`, err)
        }
      }

      // Download the merged PDF
      const mergedPdfBytes = await mergedPdf.save()  // Save the PDF as bytes
      const mergedPdfBuffer = new ArrayBuffer(mergedPdfBytes.byteLength)
      new Uint8Array(mergedPdfBuffer).set(mergedPdfBytes)
      const mergedBlob = new Blob([mergedPdfBuffer], { type: 'application/pdf' })  // Create a blob
      downloadBlob(mergedBlob, `amazon-labels-merged-${new Date().getTime()}.pdf`)  // Download the result
    } catch (error) {
      console.error('Error in batch processing:', error)  // Log the error
      alert('Failed to merge PDFs. Make sure all files processed successfully.')  // Alert the user
    } finally {
      setIsProcessing(false)  // Disable the processing state
    }
  }

  // Update Flipkart data manually
  function handleManualFlipkartUpdate() {
    if (!selectedFlipkart) return  // Return when no label is selected
    setFlipkartRows((items) =>
      items.map((item) =>
        item.id === selectedFlipkart.id  // Find the selected item
          ? {  // Update it
              ...item,
              consignmentId: manualConsignment || item.consignmentId,  // Use the manual or existing value
              boxId: manualBox || item.boxId,  // Use the manual or existing value
              status: manualConsignment && manualBox ? 'processed' : item.status,  // Mark as processed when both are filled
              message: manualConsignment && manualBox ? undefined : item.message,  // Clear the error message
            }
          : item  // Baki items unchanged
      )
    )
  }

  // Switch between Amazon and Flipkart modes
  function switchMode(next: ProcessingMode) {
    setMode(next)  // Set the new mode
    setFlipkartRows([])  // Clear Flipkart data
    setRows(next === 'amazon' ? [] : [])  // Clear Amazon data
    setSelectedId(next === 'amazon' ? 'demo-1' : '')  // Reset the selection
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        multiple
        className="hidden"
        onChange={(event) => {
          if (event.target.files && event.target.files.length > 0) {
            handleFiles(event.target.files)
          }
        }}
      />

      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <PackageCheck size={21} />
            </div>
            <div>
              <p className="font-mono text-[11px] font-bold uppercase tracking-[0.18em] text-primary">
                LabelCode Printer
              </p>
              <h1 className="text-lg font-semibold tracking-tight">Make every label count.</h1>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
              <ShieldCheck size={14} className="text-emerald-600" /> Originals stay untouched
            </span>
  
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-8">
        <section className="mb-7 flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs font-semibold text-primary">
              <Sparkles size={13} /> Vector-preserving PDF workflow
            </div>
            <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-balance md:text-4xl">
              Make product codes impossible to miss.
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
              Choose a document type, then process every label independently without rasterizing the
              original PDF.
            </p>
          </div>
        </section>

        {/* Mode Selector */}
        <section className="mb-7 rounded-2xl border border-border bg-card p-5">
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            <ScanLine size={15} /> Processing type
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <button
              type="button"
              onClick={() => switchMode('amazon')}
              className={`flex cursor-pointer items-center gap-3 rounded-xl border p-4 text-left transition ${
                mode === 'amazon'
                  ? 'border-primary bg-primary/5'
                  : 'border-border hover:bg-muted/40'
              }`}
            >
              <Boxes size={20} className="text-primary" />
              <span>
                <strong className="block text-sm">Amazon / E-commerce Shipping Label</strong>
                <small className="text-xs text-muted-foreground">
                  Add readable product codes to shipping PDFs
                </small>
              </span>
            </button>
            <button
              type="button"
              onClick={() => switchMode('flipkart')}
              className={`flex cursor-pointer items-center gap-3 rounded-xl border p-4 text-left transition ${
                mode === 'flipkart'
                  ? 'border-primary bg-primary/5'
                  : 'border-border hover:bg-muted/40'
              }`}
            >
              <ScanLine size={20} className="text-primary" />
              <span>
                <strong className="block text-sm">Flipkart Consignment Label</strong>
                <small className="text-xs text-muted-foreground">
                  Expand Box ID and relocate Consignment barcode
                </small>
              </span>
            </button>
          </div>
        </section>

        {/* Drag and Drop Zone */}
        <section
          onDragOver={handleDragOver}
          onDragEnter={handleDragOver}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className="group mb-7 flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-primary/35 bg-primary/[0.035] px-6 py-10 text-center transition hover:border-primary hover:bg-primary/[0.07]"
        >
          <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lg shadow-primary/15">
            <UploadCloud size={23} />
          </div>
          <p className="font-semibold">Drop PDF files here</p>
          <p className="mt-1 text-sm text-muted-foreground">
            or <span className="font-semibold text-primary">choose PDF files</span> ·{' '}
            {mode === 'flipkart' ? '2 labels detected per page' : 'supports multiple files'}
          </p>
          <p className="mt-3 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            {isProcessing
              ? 'Processing labels…'
              : 'Original QR codes and page geometry stay intact'}
          </p>
        </section>

        {/* Stats */}
        <div className="mb-7 grid grid-cols-2 gap-3 md:grid-cols-4">
          {statCards.map(({ label, value, Icon }) => (
            <div key={label} className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">{label}</span>
                <Icon size={15} className="text-muted-foreground" />
              </div>
              <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
            </div>
          ))}
        </div>

        {mode === 'flipkart' ? (
          <FlipkartPanel
            labels={flipkartRows}
            selected={selectedFlipkart}
            manualConsignment={manualConsignment}
            manualBox={manualBox}
            setManualConsignment={setManualConsignment}
            setManualBox={setManualBox}
            onManual={handleManualFlipkartUpdate}
            previewMode={previewMode}
            setPreviewMode={setPreviewMode}
            onDownload={downloadFlipkart}
            isProcessing={isProcessing}
          />
        ) : (
          <AmazonPanel
            rows={rows}
            selected={selected}
            selectedId={selectedId}
            setSelectedId={setSelectedId}
            onDownload={downloadAmazon}
            onDownloadAll={downloadAllAmazon}
            isProcessing={isProcessing}
          />
        )}

        <footer className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-2">
            <FolderOpen size={14} /> {stats.total} labels in current batch
          </span>
          <span>PDF quality preserved · no originals overwritten</span>
        </footer>
      </div>
    </main>
  )
}

const Status = ({ status }: { status: LabelStatus }) => {
  const labels: Record<LabelStatus, string> = {
    processing: 'Processing',
    processed: 'Processed',
    review: 'Needs review',
    failed: 'Failed',
  }

  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold ${
        status === 'processed'
          ? 'bg-emerald-100 text-emerald-800'
          : status === 'review'
          ? 'bg-amber-100 text-amber-800'
          : status === 'failed'
          ? 'bg-red-100 text-red-800'
          : 'bg-slate-100 text-slate-700'
      }`}
    >
      {labels[status]}
    </span>
  )
}

function FlipkartPanel({
  labels,
  selected,
  manualConsignment,
  manualBox,
  setManualConsignment,
  setManualBox,
  onManual,
  previewMode,
  setPreviewMode,
  onDownload,
  isProcessing,
}: FlipkartPanelProps) {
  return (
    <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
      <section className="min-w-0 rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h3 className="font-semibold">Flipkart label queue</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Each PDF page is split into two independent labels.
            </p>
          </div>
          <button
            type="button"
            onClick={onDownload}
            disabled={isProcessing || !labels.some((label) => label.status === 'processed')}
            className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Download size={14} /> Download Modified PDF
          </button>
        </div>
        <div className="max-h-[470px] overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-muted/90 text-xs text-muted-foreground">
              <tr>
                <th className="px-5 py-3">Label</th>
                <th className="px-5 py-3">Box ID</th>
                <th className="px-5 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {labels.map((label) => (
                <tr key={label.id} className="hover:bg-muted/30">
                  <td className="px-5 py-4 font-mono text-xs">
                    Page {label.pageIndex + 1} · {label.half} {label.labelNumber}
                  </td>
                  <td className="px-5 py-4 font-mono text-xs">{label.boxId || 'Enter manually'}</td>
                  <td className="px-5 py-4">
                    <Status status={label.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!labels.length && (
            <div className="p-10 text-center text-sm text-muted-foreground">
              Upload a Flipkart consignment PDF to detect labels.
            </div>
          )}
        </div>
      </section>

      <aside className="rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h3 className="font-semibold">Flipkart preview</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {selected?.boxId || 'Select a detected label'}
            </p>
          </div>
          <Settings2 size={17} className="text-muted-foreground" />
        </div>
        <div className="p-5">
          <div className="mb-4 grid grid-cols-2 rounded-lg bg-muted p-1">
            <button
              type="button"
              onClick={() => setPreviewMode('original')}
              className={`cursor-pointer rounded-md py-2 text-xs font-semibold ${
                previewMode === 'original' ? 'bg-card shadow-sm' : 'text-muted-foreground'
              }`}
            >
              Original
            </button>
            <button
              type="button"
              onClick={() => setPreviewMode('modified')}
              className={`cursor-pointer rounded-md py-2 text-xs font-semibold ${
                previewMode === 'modified' ? 'bg-card shadow-sm' : 'text-muted-foreground'
              }`}
            >
              Modified
            </button>
          </div>
          <div className="relative mx-auto aspect-[1.4/1] max-w-[460px] overflow-hidden rounded-lg border border-slate-300 bg-white p-4 text-slate-900">
            <div className="flex justify-between border-b pb-2">
              <strong className="text-xs">FLIPKART</strong>
              <span className="text-[9px]">Handle with care</span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 text-[9px]">
              <div>
                <p>To</p>
                <strong>Fulfillment Centre</strong>
                <div className="mt-3 h-12 w-12 border-4 border-slate-900" />
              </div>
              <div>
                <p>Box ID</p>
                <strong className="break-all">
                  {selected?.boxId || 'fk_mp_5200296_31445993'}
                </strong>
              </div>
            </div>
            <div className="absolute inset-x-4 top-[45%] border-y border-slate-200 py-2">
              {previewMode === 'modified' ? (
                <div className="h-14 bg-[repeating-linear-gradient(90deg,#111_0_2px,transparent_2px_5px)]" />
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  <div className="h-7 bg-[repeating-linear-gradient(90deg,#111_0_1px,transparent_1px_4px)]" />
                  <div className="h-7 bg-[repeating-linear-gradient(90deg,#111_0_1px,transparent_1px_4px)]" />
                </div>
              )}
              <p className="mt-1 text-center font-mono text-[8px]">
                {previewMode === 'modified' ? selected?.boxId : 'Consignment ID        Box ID'}
              </p>
            </div>
            <div className="absolute inset-x-4 bottom-3 flex items-end justify-between gap-3 text-[9px]">
              <p className="max-w-[55%]">From: seller address and fulfillment information</p>
              {previewMode === 'modified' && (
                <div className="text-right">
                  <div className="h-7 w-24 bg-[repeating-linear-gradient(90deg,#111_0_1px,transparent_1px_4px)]" />
                  <p className="mt-1 font-mono text-[7px]">{selected?.consignmentId || 'fk_mp_5200296'}</p>
                </div>
              )}
            </div>
          </div>

          {labels.some((label) => label.status === 'review') && (
            <div className="mt-4 space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs font-semibold text-amber-900">Manual correction</p>
              <input
                value={manualConsignment}
                onChange={(e) => setManualConsignment(e.target.value)}
                placeholder="Consignment ID"
                className="w-full rounded-md border border-amber-200 bg-white px-3 py-2 text-xs text-slate-900"
              />
              <input
                value={manualBox}
                onChange={(e) => setManualBox(e.target.value)}
                placeholder="Box ID"
                className="w-full rounded-md border border-amber-200 bg-white px-3 py-2 text-xs text-slate-900"
              />
              <button
                type="button"
                onClick={onManual}
                className="w-full cursor-pointer rounded-md bg-amber-600 px-3 py-2 text-xs font-semibold text-white"
              >
                Generate preview
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={onDownload}
            disabled={isProcessing || !labels.some((label) => label.status === 'processed')}
            className="mt-4 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-primary px-3 py-3 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Download size={15} /> Download All
          </button>
        </div>
      </aside>
    </div>
  )
}

function AmazonPanel({
  rows,
  selected,
  selectedId,
  setSelectedId,
  onDownload,
  onDownloadAll,
  isProcessing,
}: AmazonPanelProps) {
  return (
    <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-5 py-4">
          <h3 className="font-semibold">Amazon processing queue</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Order matching prioritizes the order number.
          </p>
        </div>
        <div className="overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/45 text-xs text-muted-foreground">
              <tr>
                <th className="px-5 py-3">File</th>
                <th className="px-5 py-3">Product code</th>
                <th className="w-24 px-5 py-3">QTY</th>
                <th className="px-5 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => setSelectedId(row.id)}
                  className={`cursor-pointer hover:bg-muted/30 ${
                    selected?.id === row.id ? 'bg-primary/[0.045]' : ''
                  }`}
                >
                  <td className="px-5 py-4 font-medium">{row.fileName}</td>
                  <td className="px-5 py-4 break-all font-mono text-xs">{row.productCode || '—'}</td>
                  <td className="w-24 px-5 py-4 text-center font-mono text-xs">
                    {row.amazonItems[0]?.quantity || '1'}
                  </td>
                  <td className="px-5 py-4">
                    <Status status={row.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <aside className="rounded-xl border border-border bg-card p-5">
        <h3 className="font-semibold">Label preview</h3>
        <div className="mt-5 aspect-[1.42/1] rounded-lg border border-slate-300 bg-white p-5 text-slate-900">
          <div className="h-2 w-24 bg-slate-900" />
          <div className="mt-6 h-2 w-32 bg-slate-300" />
          <div className="mt-20 border-2 border-dashed border-primary bg-primary/10 p-3 text-center font-mono text-xs font-bold text-primary">
            {selected?.productCode || 'SKU TO CONFIRM'}
          </div>
        </div>
        <div className="mt-4 space-y-2">
          <button
            type="button"
            onClick={onDownload}
            disabled={isProcessing || !selected || selected.status !== 'processed'}
            className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-primary px-3 py-3 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Download size={15} /> Download current
          </button>
          {rows.length > 1 && (
            <button
              type="button"
              onClick={onDownloadAll}
              disabled={isProcessing || rows.length === 0 || !rows.some((r) => r.status === 'processed')}
              className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 py-3 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Download size={15} /> Merge & Download all ({rows.length})
            </button>
          )}
        </div>
      </aside>
    </div>
  )
}