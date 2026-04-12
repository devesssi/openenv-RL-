/**
 * Request logging middleware.
 * Logs method, URL, status code, and response time for every request.
 */
function requestLogger(req, res, next) {
  const start = Date.now();
  const originalEnd = res.end;

  res.end = function (...args) {
    const duration = Date.now() - start;
    console.log(`[${new Date().toISOString()}] ${req.method} ${req.originalUrl} ${res.statusCode} ${duration}ms`);
    originalEnd.apply(res, args);
  };

  next();
}

module.exports = { requestLogger };
