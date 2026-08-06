<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from './api'
import {authenticated,clearSession,refreshToken,user} from './auth'
import {clearProject,selectProject,selectedProjectId} from './projects'
import ToastCenter from './components/ToastCenter.vue'
import {
  Activity,Bell,Boxes,BrainCircuit,ChartNoAxesCombined,Database,FlaskConical,ChartCandlestick,
  Check,ChevronDown,FolderKanban,LayoutDashboard,Layers3,LogOut,Plus,Search,ScrollText,
  Filter,Settings2,ShieldCheck,Sparkles,Users,WalletCards,X,
} from 'lucide-vue-next'

const route=useRoute(),router=useRouter()
const title=computed(()=>String(route.meta.title||'量化平台'))
const publicPage=computed(()=>Boolean(route.meta.public))
const projects=ref<any[]>([]),notifications=ref<any[]>([])
const searchOpen=ref(false),notificationOpen=ref(false),searchQuery=ref(''),searchResults=ref<any[]>([]),searching=ref(false)
const analysisOpen=ref(false),productionOpen=ref(false),governanceOpen=ref(false),projectMenuOpen=ref(false)
let notificationTimer:number|undefined

watch([publicPage,authenticated],async([isPublic,isAuthenticated])=>{
  if(isPublic||!isAuthenticated){projects.value=[];notifications.value=[];return}
  try{
    projects.value=(await api.get('/projects')).data
    if(!projects.value.some(project=>project.id===selectedProjectId.value)){
      if(projects.value.length)selectProject(projects.value[0].id)
      else clearProject()
    }
    await loadNotifications()
  }catch{projects.value=[]}
},{immediate:true})

async function loadNotifications(){
  if(!authenticated.value||!selectedProjectId.value)return
  notifications.value=(await api.get('/notifications',{params:{limit:10}})).data
}
const unreadCount=computed(()=>notifications.value.filter(item=>item.status==='open').length)
const activeProject=computed(()=>projects.value.find(project=>project.id===selectedProjectId.value))
function changeProject(id:string){selectProject(id);projectMenuOpen.value=false;window.location.reload()}
function closeProjectMenu(){projectMenuOpen.value=false}
async function logout(){try{if(refreshToken.value)await api.post('/auth/logout',{refresh_token:refreshToken.value})}finally{clearSession();clearProject();router.replace('/login')}}
async function search(){
  if(searchQuery.value.trim().length<2){searchResults.value=[];return}
  searching.value=true
  try{searchResults.value=(await api.get('/search',{params:{q:searchQuery.value.trim(),limit:8}})).data}
  finally{searching.value=false}
}
function openResult(item:any){searchOpen.value=false;searchQuery.value='';searchResults.value=[];router.push(item.url)}
function openNotifications(){notificationOpen.value=!notificationOpen.value;if(notificationOpen.value)loadNotifications()}

// 侧栏只将真实研究顺序作为一级入口。数据集、模型版本和预测等属于
// 研究产物或扩展分析，保留能力但默认折叠，避免用户误把它们当成必做步骤。
const coreNav=[
  ['/','研究首页',LayoutDashboard],['/data-center','1  数据与标的',Layers3],
  ['/factor-research','2  因子工程',Filter],['/datasets','3  研究数据集',Database],
  ['/experiments','4  模型研究',BrainCircuit],['/trade-workbench','5  模型交易工作台',ChartCandlestick],
  ['/backtests','6  组合回测',FlaskConical],
] as const
const analysisNav=[
  ['/models','模型仓库',Boxes],['/models/compare','模型比较',ChartNoAxesCombined],
  ['/strategies','规则策略版本',ScrollText],
] as const
const productionNav=[
  ['/predictions','批量预测',Sparkles],['/paper','模拟交易',WalletCards],
  ['/jobs','计算任务',Activity],
] as const
const governanceNav=[
  ['/projects','项目与成员',FolderKanban],['/admin/users','用户管理',Users],
  ['/admin/audit','审计日志',ShieldCheck],['/monitoring','生产运行',ChartNoAxesCombined],
] as const
const availableGovernanceNav=computed(()=>user.value?.role==='admin'?governanceNav:[])
const routeIn=(items:readonly (readonly [string,string,any])[])=>items.some(([to])=>route.path===to||route.path.startsWith(`${to}/`))
const analysisRouteActive=computed(()=>routeIn(analysisNav))
const productionRouteActive=computed(()=>routeIn(productionNav))
const governanceRouteActive=computed(()=>governanceNav.some(([to])=>route.path===to||route.path.startsWith(`${to}/`)))
watch(analysisRouteActive,active=>{if(active)analysisOpen.value=true},{immediate:true})
watch(productionRouteActive,active=>{if(active)productionOpen.value=true},{immediate:true})
watch(governanceRouteActive,active=>{if(active)governanceOpen.value=true},{immediate:true})

onMounted(()=>{notificationTimer=window.setInterval(loadNotifications,30000);document.addEventListener('click',closeProjectMenu)})
onUnmounted(()=>{window.clearInterval(notificationTimer);document.removeEventListener('click',closeProjectMenu)})
</script>

<template>
  <RouterView v-if="publicPage"/>
  <div v-else class="shell">
    <aside>
      <div class="brand"><div class="brand-mark">Q</div><div><strong>QuantForge</strong><small>RESEARCH PLATFORM</small></div></div>
      <div class="workspace-switcher">
        <label for="project-switch" class="workspace-label"><FolderKanban :size="14"/>当前项目</label>
        <div class="workspace-control" @click.stop>
          <button id="project-switch" class="workspace-trigger" type="button" :aria-expanded="projectMenuOpen" aria-haspopup="listbox" @click="projectMenuOpen=!projectMenuOpen"><span><i></i>{{activeProject?.name||'选择项目'}}</span><ChevronDown :size="16" :class="{open:projectMenuOpen}"/></button>
          <div v-if="projectMenuOpen" class="workspace-menu" role="listbox" aria-labelledby="project-switch"><button v-for="project in projects" :key="project.id" type="button" :class="{active:project.id===selectedProjectId}" :aria-selected="project.id===selectedProjectId" @click="changeProject(project.id)"><span><b>{{project.name}}</b><small>{{project.member_role||'member'}} 项目空间</small></span><Check v-if="project.id===selectedProjectId" :size="15"/></button></div>
        </div>
      </div>
      <nav>
        <p class="nav-section-label">核心流程</p>
        <RouterLink v-for="[to,label,icon] in coreNav" :key="to" :to="to"><component :is="icon" :size="18"/><span>{{label}}</span></RouterLink>
        <div class="nav-group">
          <button class="nav-group-toggle" :class="{active:analysisRouteActive}" :aria-expanded="analysisOpen" @click="analysisOpen=!analysisOpen">
            <ChartNoAxesCombined :size="18"/><span>研究资产与分析</span><ChevronDown :size="15" class="nav-chevron" :class="{open:analysisOpen}"/>
          </button>
          <div v-if="analysisOpen" class="nav-group-links">
            <RouterLink v-for="[to,label,icon] in analysisNav" :key="to" :to="to"><component :is="icon" :size="16"/><span>{{label}}</span></RouterLink>
          </div>
        </div>
        <div class="nav-group">
          <button class="nav-group-toggle" :class="{active:productionRouteActive}" :aria-expanded="productionOpen" @click="productionOpen=!productionOpen">
            <Activity :size="18"/><span>生产应用</span><ChevronDown :size="15" class="nav-chevron" :class="{open:productionOpen}"/>
          </button>
          <div v-if="productionOpen" class="nav-group-links">
            <RouterLink v-for="[to,label,icon] in productionNav" :key="to" :to="to"><component :is="icon" :size="16"/><span>{{label}}</span></RouterLink>
          </div>
        </div>
        <div v-if="availableGovernanceNav.length" class="governance-nav">
          <button class="nav-group-toggle" :class="{active:governanceRouteActive}" :aria-expanded="governanceOpen" @click="governanceOpen=!governanceOpen">
            <Settings2 :size="18"/><span>平台治理</span><ChevronDown :size="15" class="nav-chevron" :class="{open:governanceOpen}"/>
          </button>
          <div v-if="governanceOpen" class="nav-group-links">
            <RouterLink v-for="[to,label,icon] in availableGovernanceNav" :key="to" :to="to"><component :is="icon" :size="16"/><span>{{label}}</span></RouterLink>
          </div>
        </div>
      </nav>
      <div class="sidebar-foot"><span class="pulse"></span><div><b>{{user?.display_name||'研究环境在线'}}</b><small>{{user?.role||'API · Worker · Storage'}}</small></div></div>
    </aside>
    <main>
      <header><div><p>量化研究工作台</p><h1>{{title}}</h1></div><div class="head-actions">
        <button class="icon-btn" aria-label="搜索" title="全局搜索" @click="searchOpen=true"><Search :size="18"/></button>
        <div class="header-popover-anchor"><button class="icon-btn" aria-label="通知" title="通知中心" @click="openNotifications"><Bell :size="18"/><i v-if="unreadCount" class="notification-badge">{{unreadCount}}</i></button><div v-if="notificationOpen" class="header-popover"><div class="popover-head"><b>最新通知</b><button @click="notificationOpen=false"><X :size="14"/></button></div><div v-for="item in notifications.slice(0,5)" :key="item.id" class="popover-item"><i :class="item.severity"></i><div><b>{{item.title}}</b><small>{{item.message}}</small></div></div><div v-if="!notifications.length" class="empty">暂无通知</div><RouterLink to="/notifications" @click="notificationOpen=false">查看全部通知</RouterLink></div></div>
        <RouterLink class="primary link-button" to="/data-center"><Plus :size="16"/>获取数据</RouterLink>
        <button class="icon-btn" aria-label="退出登录" title="退出登录" @click="logout"><LogOut :size="18"/></button><div class="avatar">{{(user?.display_name||'W').slice(0,1)}}</div>
      </div></header>
      <RouterView/>
    </main>
    <div v-if="searchOpen" class="modal-backdrop" @click.self="searchOpen=false"><section class="search-modal"><div class="search-input"><Search :size="20"/><input v-model="searchQuery" autofocus placeholder="搜索策略、数据、实验、模型或回测" @input="search" @keyup.esc="searchOpen=false"/><button @click="searchOpen=false"><X :size="18"/></button></div><div v-if="searching" class="empty">正在搜索…</div><button v-for="item in searchResults" :key="item.type+item.id" class="search-result" @click="openResult(item)"><span>{{item.type}}</span><div><b>{{item.title}}</b><small>{{item.subtitle}}</small></div></button><div v-if="searchQuery.length>=2&&!searching&&!searchResults.length" class="empty">没有找到匹配资源。</div></section></div>
  </div>
  <ToastCenter/>
</template>
