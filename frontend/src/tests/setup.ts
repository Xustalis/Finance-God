import { Storage } from 'happy-dom'
import { afterEach, beforeEach } from 'vitest'

const testStorage = new Storage()

beforeEach(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: testStorage,
  })
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: testStorage,
  })
})

afterEach(() => {
  document.body.innerHTML = ''
  testStorage.clear()
})
