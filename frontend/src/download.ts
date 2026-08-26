import {api} from './api'

// Parquet research datasets can exceed 100 MB.  This remains finite so a
// disconnected request does not wait forever, while avoiding an arbitrary
// one-minute cutoff for an otherwise healthy transfer.
export const DOWNLOAD_TIMEOUT_MS=10*60*1000

function filenameFromDisposition(value:unknown,fallback:string){
  const header=String(value||'')
  const encoded=header.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if(encoded){
    try{return decodeURIComponent(encoded)}catch{return fallback}
  }
  return header.match(/filename="?([^";]+)"?/i)?.[1]||fallback
}

export async function downloadApiFile(endpoint:string,fallbackName:string){
  try{
    const response=await api.get(endpoint,{responseType:'blob',timeout:DOWNLOAD_TIMEOUT_MS})
    const contentType=String(response.headers['content-type']||'application/octet-stream')
    const file=response.data instanceof Blob?response.data:new Blob([response.data],{type:contentType})
    if(!file.size)throw new Error('下载文件为空，请刷新页面后重试')
    const url=window.URL.createObjectURL(file)
    const anchor=document.createElement('a')
    anchor.href=url
    anchor.download=filenameFromDisposition(response.headers['content-disposition'],fallbackName)
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(()=>window.URL.revokeObjectURL(url),1000)
  }catch(exception:any){
    const payload=exception.response?.data
    let detail=''
    if(payload instanceof Blob){
      try{detail=JSON.parse(await payload.text()).detail||''}catch{/* non-JSON response */}
    }
    const timedOut=exception?.code==='ECONNABORTED'||String(exception?.message||'').toLowerCase().includes('timeout')
    throw new Error(detail||payload?.detail||(timedOut?'下载时间较长，请检查网络后重试；大文件下载最长等待 10 分钟。':exception.message)||'下载失败，请稍后重试')
  }
}
