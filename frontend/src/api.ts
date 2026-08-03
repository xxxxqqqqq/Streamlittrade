import axios from 'axios'
import {clearSession,refreshToken,saveSession,token} from './auth'
import {clearProject,selectedProjectId} from './projects'
import {errorMessage,pushToast} from './ui'
// 浏览器始终访问同源 API；开发服务器和生产 Nginx 分别把 /api 转发给 FastAPI。
// 这样不会把 localhost 烘焙进静态产物，也能在 Docker、域名和 E2E 环境中复用同一构建。
const baseURL=import.meta.env.VITE_API_BASE_URL||'/api/v1'
export const api=axios.create({baseURL,timeout:10000})
export const rootApi=axios.create({baseURL:baseURL.replace('/api/v1',''),timeout:10000})
api.interceptors.request.use(config=>{if(token.value)config.headers.Authorization=`Bearer ${token.value}`;if(selectedProjectId.value)config.headers['X-Project-ID']=selectedProjectId.value;return config})
let refreshing:Promise<string>|null=null

// 清理全部会话上下文，并且只在尚未位于登录页时执行整页跳转。
// 这层保护可以阻止失效会话在 /login 上形成重复刷新。
function expireSession(){
  clearSession()
  clearProject()
  if(window.location.pathname!=='/login')window.location.assign('/login')
}

api.interceptors.response.use(response=>response,async error=>{
  const original=error.config
  if(error.response?.status===401&&!original?._retried&&!original?.url?.includes('/auth/')){
    if(!refreshToken.value){expireSession();return Promise.reject(error)}
    original._retried=true
    try{
      refreshing??=axios.post(`${baseURL}/auth/refresh`,{refresh_token:refreshToken.value}).then(({data})=>{saveSession(data.access_token,data.user,data.refresh_token);return data.access_token}).finally(()=>refreshing=null)
      original.headers.Authorization=`Bearer ${await refreshing}`
      return api(original)
    }catch(refreshError){expireSession();return Promise.reject(refreshError)}
  }
  if(error.response?.status!==401)pushToast(errorMessage(error),'error')
  return Promise.reject(error)
})
