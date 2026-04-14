# Zewang's Blog

个人博客站点，使用 Hugo + Stack 主题构建。

## 站点信息

- **标题**: Zewang's Blog
- **描述**: 技术笔记 · 作品展示
- **地址**: https://zewang0217.github.io/

## 部署

站点通过 GitHub Actions 自动部署到 GitHub Pages。

推送代码到 `master` 分支后会自动触发构建。

## 本地开发

```bash
# 安装 Hugo (需要 extended 版本)
# macOS: brew install hugo
# Linux: 参见 https://gohugo.io/installation/

# 本地运行
hugo server -D

# 构建
hugo --gc --minify
```

## 内容结构

```
content/
├── post/          # 博客文章
├── page/          # 独立页面（关于、归档、搜索）
└── categories/    # 分类
```

## 主题信息

基于 [Hugo Theme Stack](https://github.com/CaiJimmy/hugo-theme-stack) 主题。