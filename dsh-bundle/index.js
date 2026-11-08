/**
 * dsh-cx-bridge 的 Host 半边：一个「可见的插件条目」。
 *
 * 真正的能力由同一个 bundle 补丁里的 mcp-cx-bridge 行提供（MCP 客户端连本地 cx-bridge），
 * 这里不注册任何服务、不改任何配置，只让插件出现在「设置 → 插件」里，能被开关。
 * 任何一行抛错都会让整个条目启动失败，所以整段 try/catch。
 */
export const name = 'dsh-cx-bridge'

export function apply(ctx) {
  try {
    ctx.logger?.info?.('cx-bridge：MCP 连接由同一 bundle 的 mcp-cx-bridge 行提供')
  } catch {
    // 启动期不允许因为一行日志失败
  }
}
