import {createRouter,createWebHistory} from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import Records from './views/Records.vue'
import DatasetCreate from './views/DatasetCreate.vue'
import ExperimentCreate from './views/ExperimentCreate.vue'
import Experiments from './views/Experiments.vue'
import ModelDetail from './views/ModelDetail.vue'
import ModelCompare from './views/ModelCompare.vue'
import BacktestCreate from './views/BacktestCreate.vue'
import BacktestDetail from './views/BacktestDetail.vue'
import Login from './views/Login.vue'
import Jobs from './views/Jobs.vue'
import PaperTrading from './views/PaperTrading.vue'
import Monitoring from './views/Monitoring.vue'
import DataCenter from './views/DataCenter.vue'
import FactorResearch from './views/FactorResearch.vue'
import DataVersionDetail from './views/DataVersionDetail.vue'
import SnapshotDetail from './views/SnapshotDetail.vue'
import Strategies from './views/Strategies.vue'
import Predictions from './views/Predictions.vue'
import TradeWorkbench from './views/TradeWorkbench.vue'
import AdminUsers from './views/AdminUsers.vue'
import Projects from './views/Projects.vue'
import AuditLogs from './views/AuditLogs.vue'
import Notifications from './views/Notifications.vue'
import {authenticated,user} from './auth'

// meta.title 与顶栏五段流、段内页签保持同一套叫法：同一功能只允许一个名字，
// 避免用户在顶栏、页签和浏览器标签页里看到三种称呼。
export const router=createRouter({
  history:createWebHistory(),
  routes:[
    {path:'/login',component:Login,meta:{title:'登录',public:true}},
    {path:'/',component:Dashboard,meta:{title:'研究控制台'}},
    {path:'/data-center',component:DataCenter,meta:{title:'获取数据'}},
    {path:'/factor-research',component:FactorResearch,meta:{title:'因子研究'}},
    {path:'/data-center/versions/:id',component:DataVersionDetail,meta:{title:'数据质量详情'}},
    {path:'/data-center/snapshots/:id',component:SnapshotDetail,meta:{title:'特征快照详情'}},
    {path:'/paper',component:PaperTrading,meta:{title:'模拟盘'}},
    {path:'/monitoring',component:Monitoring,meta:{title:'生产运行',admin:true}},
    {path:'/notifications',component:Notifications,meta:{title:'通知中心'}},
    {path:'/projects',component:Projects,meta:{title:'项目与成员',admin:true}},
    {path:'/admin/users',component:AdminUsers,meta:{title:'用户管理',admin:true}},
    {path:'/admin/audit',component:AuditLogs,meta:{title:'审计日志',admin:true}},
    {path:'/datasets/new',component:DatasetCreate,meta:{title:'创建数据集'}},
    {path:'/experiments/new',component:ExperimentCreate,meta:{title:'创建训练实验'}},
    {path:'/models/compare',component:ModelCompare,meta:{title:'模型比较'}},
    {path:'/models/:id',component:ModelDetail,meta:{title:'模型详情'}},
    {path:'/models/:id/trade-workbench',component:TradeWorkbench,meta:{title:'模型交易工作台'}},
    // 交易工作台是模型的下钻页，不再是一级入口；旧链接统一回到模型仓库。
    {path:'/trade-workbench',redirect:'/models'},
    {path:'/backtests/new',component:BacktestCreate,meta:{title:'创建回测'}},
    {path:'/backtests/:id',component:BacktestDetail,meta:{title:'回测报告'}},
    {path:'/backtests',component:Records,props:{kind:'backtests'},meta:{title:'回测中心'}},
    {path:'/datasets',component:Records,props:{kind:'datasets'},meta:{title:'研究数据集'}},
    {path:'/experiments',component:Experiments,meta:{title:'训练实验'}},
    {path:'/models',component:Records,props:{kind:'models'},meta:{title:'模型仓库'}},
    {path:'/predictions',component:Predictions,meta:{title:'批量预测'}},
    {path:'/strategies',component:Strategies,meta:{title:'策略版本'}},
    {path:'/jobs',component:Jobs,meta:{title:'任务中心'}},
  ],
})

router.beforeEach(to=>{
  if(!to.meta.public&&!authenticated.value)return{path:'/login',query:{redirect:to.fullPath}}
  if(to.meta.admin&&user.value?.role!=='admin')return'/'
  if(to.path==='/login'&&authenticated.value)return'/'
  return true
})
