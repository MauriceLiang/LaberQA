import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElContainer,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElHeader,
  ElMain,
  ElSkeleton,
  ElTag,
} from 'element-plus'

import App from './App.vue'
import router from './router'
import 'element-plus/dist/index.css'
import './styles.css'

const app = createApp(App)

app.use(createPinia()).use(router)
app.use(ElAlert)
app.use(ElButton)
app.use(ElCard)
app.use(ElContainer)
app.use(ElDescriptions)
app.use(ElDescriptionsItem)
app.use(ElEmpty)
app.use(ElHeader)
app.use(ElMain)
app.use(ElSkeleton)
app.use(ElTag)
app.mount('#app')
