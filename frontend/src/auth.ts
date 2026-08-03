import {computed,ref} from 'vue'

const TOKEN_KEY='quant_access_token'
const USER_KEY='quant_user'
const REFRESH_KEY='quant_refresh_token'
export const token=ref(sessionStorage.getItem(TOKEN_KEY)||'')
export const refreshToken=ref(sessionStorage.getItem(REFRESH_KEY)||'')
export const user=ref<any>(JSON.parse(sessionStorage.getItem(USER_KEY)||'null'))
export const authenticated=computed(()=>Boolean(token.value))

export function saveSession(accessToken:string,currentUser:any,newRefreshToken?:string){token.value=accessToken;user.value=currentUser;sessionStorage.setItem(TOKEN_KEY,accessToken);sessionStorage.setItem(USER_KEY,JSON.stringify(currentUser));if(newRefreshToken){refreshToken.value=newRefreshToken;sessionStorage.setItem(REFRESH_KEY,newRefreshToken)}}
export function clearSession(){token.value='';refreshToken.value='';user.value=null;sessionStorage.removeItem(TOKEN_KEY);sessionStorage.removeItem(REFRESH_KEY);sessionStorage.removeItem(USER_KEY)}
