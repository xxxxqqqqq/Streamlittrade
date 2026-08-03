import {ref} from 'vue'

const PROJECT_KEY='quant_project_id'
export const selectedProjectId=ref(sessionStorage.getItem(PROJECT_KEY)||'')
export function selectProject(id:string){selectedProjectId.value=id;sessionStorage.setItem(PROJECT_KEY,id)}
export function clearProject(){selectedProjectId.value='';sessionStorage.removeItem(PROJECT_KEY)}
