<script setup lang="ts">
/** 未匹配路由的兜底页面。 */
</script>

<template>
  <section class="not-found">
    <h1>页面不存在</h1>
    <p>请求的地址没有对应页面。</p>
    <RouterLink to="/">返回工作台首页</RouterLink>
  </section>
</template>

<style scoped>
.not-found {
  max-width: 32rem;
}
</style>
