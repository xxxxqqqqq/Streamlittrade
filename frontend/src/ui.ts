import {ref} from 'vue'

export type Toast={id:number;kind:'error'|'success'|'info';message:string}
export const toasts=ref<Toast[]>([])
let sequence=0

export function pushToast(message:string,kind:Toast['kind']='info'){
  const item={id:++sequence,kind,message}
  toasts.value.push(item)
  window.setTimeout(()=>dismissToast(item.id),5000)
}

export function dismissToast(id:number){
  toasts.value=toasts.value.filter(item=>item.id!==id)
}

export function errorMessage(error:any){
  const detail=error?.response?.data?.detail
  if(Array.isArray(detail))return detail.map(item=>item.msg).join('；')
  if(!detail&&error?.response?.status===502)return '服务暂时无法装配工作台数据，请稍后重试。'
  return detail||error?.message||'操作失败，请稍后重试'
}
