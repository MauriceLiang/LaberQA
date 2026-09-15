<template>
  <el-container class="app-shell">
    <el-header class="app-header">
      <div class="brand-mark">劳</div>
      <div>
        <p class="eyebrow">LABOR RIGHTS ASSISTANT</p>
        <h1>劳动权益咨询问答台</h1>
      </div>
      <nav class="app-nav" aria-label="主导航">
        <RouterLink to="/">AI 咨询</RouterLink>
        <RouterLink to="/system">系统状态</RouterLink>
        <RouterLink to="/documents">资料管理</RouterLink>
        <RouterLink to="/missing-knowledge">知识缺口</RouterLink>
        <RouterLink to="/evaluations">问答评测</RouterLink>
      </nav>
      <el-tag type="success" effect="plain">Phase 8</el-tag>
    </el-header>
    <el-main class="app-main">
      <router-view />
      <p class="legal-note">本系统用于信息辅助，不替代正式法律意见。</p>
    </el-main>
  </el-container>
</template>
