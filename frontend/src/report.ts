import { invoke } from '@tauri-apps/api/core'

const html = localStorage.getItem('rka-report-print')
localStorage.removeItem('rka-report-print')
if (!html) {
  document.body.textContent = '没有可打印的技术记录。请从报告中心重新生成。'
} else {
  const report = new DOMParser().parseFromString(html, 'text/html')
  document.head.innerHTML = report.head.innerHTML
  document.body.innerHTML = report.body.innerHTML
  const style = document.createElement('style')
  style.textContent = '.print-toolbar{position:fixed;top:12px;right:12px;padding:10px 18px;border:0;border-radius:6px;background:#0369a1;color:white;font:600 13px system-ui;cursor:pointer;box-shadow:0 4px 16px #0004}@media print{.print-toolbar{display:none}}'
  document.head.append(style)
  const button = document.createElement('button')
  button.className = 'print-toolbar'
  button.textContent = '打印 / 保存 PDF'
  button.onclick = () => { void invoke('print_report_window') }
  document.body.prepend(button)
}
