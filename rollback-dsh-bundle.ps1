# 出问题时回退：撤销 dsh-cx-bridge 插件（恢复手写 MCP 补丁 + 从 profile 移除 bundle）
$ErrorActionPreference = 'Stop'
$prof = Join-Path $env:USERPROFILE '.dsh\profiles\desktop'
$bak  = Get-ChildItem $prof -Filter 'cordis.patch.yml.bak-before-bundle-*' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($bak) { Copy-Item $bak.FullName (Join-Path $prof 'cordis.patch.yml') -Force; Write-Host "已恢复 $($bak.Name)" } else { Write-Host '没找到备份，跳过补丁恢复' }
python - <<'PY'
import json, pathlib
p = pathlib.Path.home() / '.dsh' / 'profiles' / 'desktop' / 'package.json'
d = json.loads(p.read_text(encoding='utf-8'))
d.get('dependencies', {}).pop('dsh-cx-bridge', None)
b = d.get('dsh', {}).get('profile', {}).get('bundles', [])
while 'dsh-cx-bridge' in b: b.remove('dsh-cx-bridge')
p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('已从依赖和 bundle 列表中移除 dsh-cx-bridge')
PY
Write-Host '回退完成，重启 DSH 生效。'
