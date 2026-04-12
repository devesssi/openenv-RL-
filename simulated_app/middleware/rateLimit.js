/**
 * Simple in-memory rate limiter middleware.
 * Tracks request counts per IP within a sliding window.
 */
const requestCounts = new Map();

function rateLimiter(req, res, next) {
  const ip = req.ip || req.connection.remoteAddress || 'unknown';
  const now = Date.now();
  const windowMs = 60000; // 1 minute window
  const maxRequests = 100;

  if (!requestCounts.has(ip)) {
    requestCounts.set(ip, { count: 1, windowStart: now });
    return next();
  }

  const record = requestCounts.get(ip);

  if (now - record.windowStart > windowMs) {
    // Reset window
    record.count = 1;
    record.windowStart = now;
    return next();
  }

  record.count++;

  if (record.count > maxRequests) {
    return res.status(429).json({
      error: 'Too many requests',
      retryAfter: Math.ceil((record.windowStart + windowMs - now) / 1000)
    });
  }

  next();
}

module.exports = { rateLimiter };
