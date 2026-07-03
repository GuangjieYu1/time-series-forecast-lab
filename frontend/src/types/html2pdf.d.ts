declare module "html2pdf.js" {
  interface Html2PdfChain {
    set(options: Record<string, unknown>): Html2PdfChain;
    from(source: HTMLElement): Html2PdfChain;
    save(): Promise<void>;
  }

  export default function html2pdf(): Html2PdfChain;
}
