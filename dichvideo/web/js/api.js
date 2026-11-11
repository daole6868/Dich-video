// Gọi API của máy chủ cục bộ. Lỗi được ném ra kèm thông điệp tiếng Việt từ máy chủ.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, url, { json, body, headers } = {}) {
  const opts = { method, headers: { ...(headers || {}) } };
  if (json !== undefined) {
    opts.body = JSON.stringify(json);
    opts.headers["Content-Type"] = "application/json";
  } else if (body !== undefined) {
    opts.body = body;
    opts.headers["Content-Type"] = opts.headers["Content-Type"] || "application/octet-stream";
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    throw new ApiError("Không kết nối được tới ứng dụng. Hãy kiểm tra cửa sổ chương trình còn mở không.", 0);
  }
  if (!res.ok) {
    let message = `Lỗi ${res.status}`;
    try {
      const data = await res.json();
      if (data && data.error) message = data.error;
    } catch (e) { /* không phải JSON */ }
    throw new ApiError(message, res.status);
  }
  return res;
}

export const api = {
  async get(url) { return (await request("GET", url)).json(); },
  async post(url, json) { return (await request("POST", url, { json: json ?? {} })).json(); },
  async put(url, json) { return (await request("PUT", url, { json })).json(); },
  async patch(url, json) { return (await request("PATCH", url, { json })).json(); },
  async del(url) { return (await request("DELETE", url)).json(); },
  async postRaw(url, body) { return (await request("POST", url, { body })).json(); },
  async blob(method, url, json) { return (await request(method, url, json === undefined ? {} : { json })).blob(); },

  // Tải tệp lớn lên bằng XHR để có tiến độ; trả về { promise, abort }.
  upload(url, file, onProgress) {
    const xhr = new XMLHttpRequest();
    const promise = new Promise((resolve, reject) => {
      xhr.open("PUT", url);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (e) { /* bỏ qua */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new ApiError((data && data.error) || `Lỗi ${xhr.status} khi tải tệp lên`, xhr.status));
      };
      xhr.onerror = () => reject(new ApiError("Mất kết nối khi đang tải tệp lên.", 0));
      xhr.onabort = () => reject(new ApiError("Đã huỷ tải lên.", 0));
      xhr.send(file);
    });
    return { promise, abort: () => xhr.abort() };
  },
};
