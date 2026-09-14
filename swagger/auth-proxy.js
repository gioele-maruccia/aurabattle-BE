#!/usr/bin/env node

/**
 * Cognito Authentication Proxy for Swagger UI
 * Environment-based configuration (dev/prod)
 */

const http = require('http');
const https = require('https');
const { spawn } = require('child_process');
const { URL } = require('url');

// ============================================================================
// ENVIRONMENT CONFIGURATION
// ============================================================================

const ENV = process.env.ENV || 'dev';

const ENVIRONMENTS = {
  dev: {
    cognito: {
      users: {
        region: 'eu-south-1',
        userPoolId: 'eu-south-1_0oK9agPYd',
        clientId: '79g67hnuepfuoh1fnk4d98jfpu',
      }
    },
    apiGateways: {
      backoffice: 'https://v7m02xrzyh.execute-api.eu-south-1.amazonaws.com/dev',
      documents: 'https://fwizu30er5.execute-api.eu-south-1.amazonaws.com/dev',
      userProfile: 'https://vl053j522a.execute-api.eu-south-1.amazonaws.com/dev',
      companies: ' https://60yduam5il.execute-api.eu-south-1.amazonaws.com/dev',
      jobListings: 'https://0kur695aae.execute-api.eu-south-1.amazonaws.com/dev',
      bookings: 'https://abala746ia.execute-api.eu-south-1.amazonaws.com/dev',
      referenceData: 'https://8b9akxu7z4.execute-api.eu-south-1.amazonaws.com/dev',
      contracts: 'https://ua6afz3kzb.execute-api.eu-south-1.amazonaws.com/dev',
      chat: 'https://57s2xhuuo4.execute-api.eu-south-1.amazonaws.com/dev',
      supportChat: 'https://gru7fsup3e.execute-api.eu-south-1.amazonaws.com/dev',
      userApi: 'https://8y5y7khdp8.execute-api.eu-south-1.amazonaws.com/dev'
    }
  },
  prod: {
    cognito: {
      users: {
        region: 'eu-south-1',
        userPoolId: 'eu-south-1_iCBtUlJO6',
        clientId: '20gudbvdh3hesbge0c8od0202b',
      }
    },
    apiGateways: {
      backoffice: 'https://b59g0m7g4j.execute-api.eu-south-1.amazonaws.com/prod',
      documents: 'https://uuob2qxq6i.execute-api.eu-south-1.amazonaws.com/prod',
      userProfile: 'https://0h1mgdk871.execute-api.eu-south-1.amazonaws.com/prod', 
      companies: 'https://bn6bl5uqoa.execute-api.eu-south-1.amazonaws.com/prod',
      jobListings: 'https://m0vjkzixzk.execute-api.eu-south-1.amazonaws.com/prod',
      bookings: 'https://2cn7qkhhhj.execute-api.eu-south-1.amazonaws.com/prod',
      referenceData: 'https://10bkq6xynh.execute-api.eu-south-1.amazonaws.com/prod',
      contracts: 'https://dfuatoula1.execute-api.eu-south-1.amazonaws.com/prod',
      chat: '',
      supportChat: '',
      userApi: 'https://o2hw6imm12.execute-api.eu-south-1.amazonaws.com/prod'
    }
  }
};

const CONFIG = {
  environment: ENV,
  cognito: ENVIRONMENTS[ENV].cognito,
  apiGateways: ENVIRONMENTS[ENV].apiGateways,
  proxy: { port: 8081 },
  
  // Route mapping: which API Gateway to use for each path pattern
  routeMapping: {
    '/auth/': 'local',
    
    // Profile endpoints (more specific first)
    '/profile': 'userApi',
    '/settings': 'userApi',
    '/verifications': 'userApi',
    '/ratings': 'userApi',
    '/bookmarks/': 'userApi',
    
    // Chat endpoints (more specific first)
    '/chats/[^/]+/messages/[^/]+/state': 'chat',    // PATCH /chats/{chatId}/messages/{messageId}/state
    '/chats/[^/]+/messages/[^/]+/sticker': 'chat',  // POST /chats/{chatId}/messages/{messageId}/sticker
    '/chats/[^/]+/messages': 'chat',                // GET/POST /chats/{chatId}/messages
    '/chats/[^/]+/upload-url': 'chat',              // GET /chats/{chatId}/upload-url
    '/chats/[^/]+/download-url': 'chat',            // GET /chats/{chatId}/download-url
    '/chats/[^/]+/request-help': 'chat',            // POST /chats/{chatId}/request-help
    '/chats/[^/]+/status': 'chat',                  // PATCH /chats/{chatId}/status
    '/chats': 'chat',                               // GET/POST /chats
    
    // Support Chat endpoints
    '/support-chats/[^/]+/messages/[^/]+/state': 'supportChat',     // PATCH /support-chats/{supportChatId}/messages/{messageId}/state
    '/support-chats/[^/]+/messages/[^/]+/sticker': 'supportChat',   // POST /support-chats/{supportChatId}/messages/{messageId}/sticker
    '/support-chats/[^/]+/messages': 'supportChat',                 // GET/POST /support-chats/{supportChatId}/messages
    '/support-chats/[^/]+/upload-url': 'supportChat',               // GET /support-chats/{supportChatId}/upload-url
    '/support-chats/[^/]+/download-url': 'supportChat',             // GET /support-chats/{supportChatId}/download-url
    '/support-chats/[^/]+/status': 'supportChat',                   // PATCH /support-chats/{supportChatId}/status
    '/support-chats': 'supportChat',                                 // GET/POST /support-chats
    
    '/contracts/': 'contracts',
    '/reference-data': 'referenceData',
    '/bookings/blackout/listing/': 'bookings',
    '/bookings/blackout/': 'bookings',
    '/bookings/blackout/[^/]+': 'bookings',
    '/bookings/availability/': 'bookings',
    '/bookings/worker/': 'bookings',
    '/bookings/company/': 'bookings',
    '/bookings/listing/': 'bookings',
    '/bookings/[^/]+/status': 'bookings',
    '/bookings/[^/]+/cancel': 'bookings',
    '/bookings/[^/]+': 'bookings',
    '/bookings': 'bookings',
    '/workers/calendar': 'bookings',
    '/listings/company/': 'jobListings',
    '/listings/my': 'jobListings',
    '/listings/[^/]+/publish': 'jobListings',
    '/listings/[^/]+/pause': 'jobListings',
    '/listings/[^/]+/close': 'jobListings',
    '/listings/[^/]+': 'jobListings',
    '/listings': 'jobListings',
    '/companies/my-applicable-job-roles': 'companies',
    '/companies/public/': 'companies',
    '/companies/[^/]+': 'companies',
    '/companies': 'companies',
    '/documents/user/': 'backoffice',
    '/documents/download/': 'backoffice',
    '/documents/stats': 'backoffice',
    '/users/search': 'backoffice',
    '/documents/upload-url': 'documents',
    '/user/': 'documents',
    '/initiate-upgrade': 'userProfile',
    '/documents': 'backoffice',
  }
};

// ============================================================================
// Cognito Authentication
// ============================================================================

class CognitoAuth {
  constructor(poolConfig) {
    this.region = poolConfig.region;
    this.userPoolId = poolConfig.userPoolId;
    this.clientId = poolConfig.clientId;
  }

  async login(username, password) {
    return new Promise((resolve, reject) => {
      const args = [
        'cognito-idp', 'admin-initiate-auth',
        '--user-pool-id', this.userPoolId,
        '--client-id', this.clientId,
        '--auth-flow', 'ADMIN_NO_SRP_AUTH',
        '--auth-parameters', `USERNAME=${username},PASSWORD=${password}`,
        '--region', this.region,
        '--output', 'json'
      ];

      const aws = spawn('aws', args);
      let stdout = '';
      let stderr = '';

      aws.stdout.on('data', (data) => stdout += data.toString());
      aws.stderr.on('data', (data) => stderr += data.toString());

      aws.on('close', (code) => {
        if (code !== 0) {
          reject(new Error(stderr || 'AWS CLI authentication failed'));
          return;
        }

        try {
          const response = JSON.parse(stdout);
          if (!response.AuthenticationResult) {
            reject(new Error('No authentication result'));
            return;
          }

          resolve({
            idToken: response.AuthenticationResult.IdToken,
            accessToken: response.AuthenticationResult.AccessToken,
            refreshToken: response.AuthenticationResult.RefreshToken,
            expiresIn: response.AuthenticationResult.ExpiresIn || 3600,
            tokenType: 'Bearer',
          });
        } catch (error) {
          reject(new Error('Failed to parse AWS CLI response'));
        }
      });
    });
  }
}

// ============================================================================
// Proxy Server
// ============================================================================

class ProxyServer {
  constructor(config) {
    this.config = config;
    this.auth = new CognitoAuth(config.cognito.users);
  }

  start() {
    const server = http.createServer((req, res) => this.handleRequest(req, res));

    server.listen(this.config.proxy.port, () => {
      this.printStartupInfo();
    });

    server.on('error', (error) => {
      console.error('Server error:', error);
      if (error.code === 'EADDRINUSE') {
        console.error(`Port ${this.config.proxy.port} is already in use`);
      }
      process.exit(1);
    });
  }

  async handleRequest(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, PATCH, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

    if (req.method === 'OPTIONS') {
      res.writeHead(200);
      res.end();
      return;
    }

    const url = new URL(req.url, `http://localhost:${this.config.proxy.port}`);

    if (url.pathname === '/auth/login' || 
        url.pathname === '/auth/login/users' ||
        url.pathname === '/auth/login/backoffice') {
      await this.handleLogin(req, res);
      return;
    }

    this.proxyToApiGateway(req, res);
  }

  async handleLogin(req, res) {
    try {
      const body = await this.readBody(req);
      const { username, password } = JSON.parse(body);

      if (!username || !password) {
        this.sendError(res, 400, 'Username and password required');
        return;
      }

      console.log(`[AUTH] Login attempt: ${username}`);
      const tokens = await this.auth.login(username, password);
      console.log(`[AUTH] Success: ${username}`);
      
      this.sendJson(res, 200, tokens);
    } catch (error) {
      console.error(`[AUTH] Failed:`, error.message);
      this.sendError(res, 401, error.message);
    }
  }

  determineApiGateway(pathname) {
    // Remove query string from pathname
    const pathOnly = pathname.split('?')[0];
    
    for (const [pattern, gateway] of Object.entries(this.config.routeMapping)) {
      const regex = new RegExp('^' + pattern);
      if (regex.test(pathOnly)) {
        return gateway;
      }
    }
    return 'backoffice';
  }

  proxyToApiGateway(req, res) {
    const pathname = new URL(req.url, `http://localhost:${this.config.proxy.port}`).pathname;
    const gatewayType = this.determineApiGateway(pathname);
    
    if (gatewayType === 'local') {
      this.sendError(res, 404, 'Endpoint not found');
      return;
    }
    
    const apiGatewayUrl = this.config.apiGateways[gatewayType];
    
    if (!apiGatewayUrl) {
      console.error(`[PROXY] No API Gateway URL configured for: ${gatewayType}`);
      this.sendError(res, 502, `API Gateway not configured for ${gatewayType}`);
      return;
    }
    
    const apiUrl = new URL(apiGatewayUrl);
    const basePath = apiUrl.pathname.replace(/\/$/, '');
    const incomingPath = req.url.startsWith('/') ? req.url : `/${req.url}`;
    const fullPath = `${basePath}${incomingPath}`;

    const inHeaders = Object.fromEntries(
      Object.entries(req.headers).map(([k, v]) => [k.toLowerCase(), v])
    );

    const blocked = new Set(['host', 'x-amz-date', 'x-amz-security-token', 'x-amz-content-sha256', 'authorization']);
    const fwdHeaders = {};
    for (const [k, v] of Object.entries(inHeaders)) {
      if (!blocked.has(k)) fwdHeaders[k] = v;
    }

    if (inHeaders['authorization']) {
      const val = inHeaders['authorization'].toString().trim();
      if (val.includes(',')) {
        const parts = val.split(',').map(s => s.trim());
        const bearer = parts.find(p => /^Bearer\s+/i.test(p));
        fwdHeaders['Authorization'] = bearer || parts[0];
      } else {
        fwdHeaders['Authorization'] = val;
      }
    }

    const options = {
      hostname: apiUrl.hostname,
      port: 443,
      path: fullPath,
      method: req.method,
      headers: {
        ...fwdHeaders,
        'x-forwarded-host': `localhost:${this.config.proxy.port}`,
        'x-forwarded-proto': 'http',
      },
    };

    console.log(`[PROXY] ${req.method} ${pathname} -> [${gatewayType}] https://${apiUrl.hostname}${fullPath}`);

    const proxyReq = https.request(options, (proxyRes) => {
      const chunks = [];
      proxyRes.on('data', (c) => chunks.push(c));
      proxyRes.on('end', () => {
        const body = Buffer.concat(chunks);
        const headers = {
          ...proxyRes.headers,
          'access-control-allow-origin': '*',
          'access-control-allow-methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
          'access-control-allow-headers': 'Content-Type, Authorization, x-api-key',
        };
        res.writeHead(proxyRes.statusCode, headers);
        res.end(body);

        if (proxyRes.statusCode >= 400) {
          console.error(`[UPSTREAM ${proxyRes.statusCode}] ${body.toString('utf8')}`);
        }
      });
    });

    proxyReq.on('error', (error) => {
      console.error(`[PROXY] Error:`, error.message);
      this.sendError(res, 502, 'Proxy error: ' + error.message);
    });

    req.pipe(proxyReq);
  }

  readBody(req) {
    return new Promise((resolve) => {
      let body = '';
      req.on('data', (chunk) => { body += chunk; });
      req.on('end', () => { resolve(body); });
    });
  }

  sendJson(res, statusCode, data) {
    res.writeHead(statusCode, { 
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*'
    });
    res.end(JSON.stringify(data, null, 2));
  }

  sendError(res, statusCode, message) {
    this.sendJson(res, statusCode, {
      statusCode,
      message,
      error: statusCode >= 500 ? 'INTERNAL_ERROR' : 'CLIENT_ERROR',
    });
  }

  printStartupInfo() {
    console.log('\n' + '='.repeat(70));
    console.log(`  COGNITO AUTH PROXY - ${this.config.environment.toUpperCase()} ENVIRONMENT`);
    console.log('='.repeat(70));
    console.log(`\n  Proxy Server:    http://localhost:${this.config.proxy.port}`);
    console.log('\n  API Gateways:');
    Object.entries(this.config.apiGateways).forEach(([name, url]) => {
      console.log(`    ${name.padEnd(15)} ${url || '(not configured)'}`);
    });
    console.log('\n  Cognito User Pool:');
    console.log(`    Region:        ${this.config.cognito.users.region}`);
    console.log(`    User Pool ID:  ${this.config.cognito.users.userPoolId}`);
    console.log(`    Client ID:     ${this.config.cognito.users.clientId}`);
    console.log('\n' + '='.repeat(70) + '\n');
  }
}

// Check AWS CLI
const { execSync } = require('child_process');
try {
  execSync('aws --version', { stdio: 'ignore' });
} catch (error) {
  console.error('\nERROR: AWS CLI not found. Please install it.\n');
  process.exit(1);
}

// Start server
const proxy = new ProxyServer(CONFIG);
proxy.start();