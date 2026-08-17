// REST 访问封装：统一错误 {code, message}（§9）
async function request(method, url, body) {
  const options = { method, headers: {} }
  if (body !== undefined) {
    if (body instanceof FormData) {
      options.body = body
    } else {
      options.headers['Content-Type'] = 'application/json'
      options.body = JSON.stringify(body)
    }
  }
  const resp = await fetch(url, options)
  let data = null
  try {
    data = await resp.json()
  } catch {
    data = null
  }
  if (!resp.ok) {
    const err = new Error((data && data.message) || `请求失败(${resp.status})`)
    err.code = (data && data.code) || 'HTTP_ERROR'
    err.status = resp.status
    throw err
  }
  return data
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body ?? {}),
  put: (url, body) => request('PUT', url, body ?? {}),
  del: (url) => request('DELETE', url),
  upload: (url, file) => {
    const form = new FormData()
    form.append('file', file)
    return request('POST', url, form)
  },
}
