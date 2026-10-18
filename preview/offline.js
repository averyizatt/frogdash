/* Preview only, loaded first: the dash's own service (/camera/status, /screen, /terminal,
   ...) does not exist on the published preview. Requests to it fail here, at once and
   without touching the network, as they do when the preview is opened as a file. */
(() => {
  const fetchFromNetwork = window.fetch.bind(window);
  window.fetch = (resource, options) => {
    const url = typeof resource === 'string' ? resource : resource?.url || '';
    if (url.startsWith('/')) return Promise.reject(new TypeError('Not available in the preview'));
    return fetchFromNetwork(resource, options);
  };
})();
