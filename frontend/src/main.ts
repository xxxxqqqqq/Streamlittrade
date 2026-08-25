import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import './style.css'
import './workspace-switcher.css'
import './flow-connectors.css'
import './workflow.css'
import './background-tasks.css'
import './report.css'
import './login.css'
import './jobs.css'
import './model-lifecycle.css'
import './paper.css'
import './monitoring.css'
import './product.css'
import './trade-workbench.css'
import './core-flow-v2.css'

const app=createApp(App)
app.use(router)

// 等待首个路由解析完成，确保 App 首次渲染时能正确识别登录页。
// 否则 route.meta 仍为空，App 会误把 /login 当成受保护页面。
router.isReady().then(()=>app.mount('#app'))
