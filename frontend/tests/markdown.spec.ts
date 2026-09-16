import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MarkdownContent from '@/components/chat/MarkdownContent.vue'
import { parseMarkdown } from '@/utils/markdown'

describe('MarkdownContent', () => {
  it('renders headings, emphasis, and lists from an assistant answer', () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '## 简要结论\n\n**重点**：请保留证据。\n\n- 工资流水\n- **劳动合同**',
      },
    })

    expect(wrapper.find('h2').text()).toBe('简要结论')
    expect(wrapper.find('strong').text()).toBe('重点')
    expect(wrapper.findAll('li')).toHaveLength(2)
    expect(wrapper.findAll('strong')[1].text()).toBe('劳动合同')
  })

  it('keeps unmatched markers as text and does not render raw HTML', () => {
    const content = '<script>alert(1)</script>\n\n未闭合的 **重点'
    const wrapper = mount(MarkdownContent, { props: { content } })

    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.text()).toContain('<script>alert(1)</script>')
    expect(wrapper.text()).toContain('未闭合的 **重点')
  })

  it('preserves line breaks inside a paragraph', () => {
    const blocks = parseMarkdown('第一行\n第二行')

    expect(blocks).toHaveLength(1)
    expect(blocks[0]).toEqual({
      type: 'paragraph',
      tokens: [
        { type: 'text', text: '第一行' },
        { type: 'line-break' },
        { type: 'text', text: '第二行' },
      ],
    })
  })
})
