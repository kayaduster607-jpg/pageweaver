'use strict'

// Execute the actual inline browser script with a minimal DOM and fake API.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const source = fs.readFileSync(path.join(__dirname, '..', 'image_to_pdf_server.py'), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)[1]

function createBrowser(fetch) {
  const fields = new Map()
  function element(id) {
    if (!fields.has(id)) {
      fields.set(id, {
        value: '', textContent: '', innerHTML: '', disabled: false,
        classList: { add() {}, remove() {} }, appendChild() {},
      })
    }
    return fields.get(id)
  }
  const context = vm.createContext({
    document: { getElementById: element, createElement: () => element('created'),
      body: { appendChild() {}, removeChild() {} } },
    URLSearchParams, fetch, setTimeout() {}, alert() {},
  })
  vm.runInContext(script, context)
  return { context, element }
}

test('URL template is displayed as text and page zero survives the form', async () => {
  const template = 'https://example.test/<img src=x onerror=alert(1)>/0001.png'
  let requestUrl
  const browser = createBrowser(async (url) => {
    if (url.startsWith('/api/start')) {
      requestUrl = url
      return { json: async () => ({ task_id: 'demo', template, descramble: 'none' }) }
    }
    return new Promise(() => {})
  })
  browser.element('url-input').value = 'https://example.test/book/0001.png'
  browser.element('start-input').value = '0'
  await vm.runInContext('startTask()', browser.context)
  assert.equal(new URL(requestUrl, 'http://127.0.0.1').searchParams.get('start'), '0')
  assert.ok(browser.element('progress').textContent.includes(template))
  assert.equal(browser.element('progress').innerHTML, '')
})

test('partial output is labeled with an error and an incomplete download caption', async () => {
  const browser = createBrowser(async () => ({ json: async () => ({
    done: true, total: 1, images: [], error: 'synthetic missing page',
  }) }))
  vm.runInContext("taskId = 'demo'", browser.context)
  await vm.runInContext('pollTask()', browser.context)
  assert.ok(browser.element('progress').textContent.includes('含错误'))
  assert.ok(browser.element('progress').textContent.includes('synthetic missing page'))
  assert.ok(browser.element('download-btn').textContent.includes('可能不完整'))
})

test('successful output restores the normal download caption', async () => {
  const browser = createBrowser(async () => ({ json: async () => ({
    done: true, total: 2, images: [], error: null,
  }) }))
  browser.element('download-btn').textContent = 'old partial caption'
  vm.runInContext("taskId = 'demo'", browser.context)
  await vm.runInContext('pollTask()', browser.context)
  assert.equal(browser.element('download-btn').textContent, '下载 PDF')
})
