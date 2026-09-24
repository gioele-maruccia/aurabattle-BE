#!/usr/bin/env node

/**
 * Cognito Authentication Proxy for Swagger UI
 * Environment-based configuration (dev-aurabattle/prod-aurabattle)
 */

const http = require('http');
const https = require('https');
const { spawn } = require('child_process');
const { URL } = require('url');

// ============================================================================
// ENVIRONMENT CONFIGURATION
// ============================================================================

const ENV = process.env.ENV || 'dev-aurabattle';

const ENVIRONMENTS = {
  'dev-aurabattle': {
    cognito: {
      users: {
        region: 'eu-south-1',
        userPoolId: 'eu-south-1_ULXAFvzY9',
        clientId: '1si0vr079rbrvtck9ht4cpob78',
      }
    },
    apiGateways: {
      // Aggiungi qui i gateway man mano che deployi gli altri servizi
      userApi: 'https://hk3y2bs3ph.execute-api.eu-south-1.amazonaws.com/dev-aurabattle/v1',
      backoffice: '',
      battles: 'https://ln6a4z3lp4.execute-api.eu-south-1.amazonaws.com/dev-aurabattle/v1',
      participations: '',
    }
  },
  'prod-aurabattle': {
    cognito: {
      users: {
        region: 'eu-south-1',
        userPoolId: '',
        clientId: '',
      }
    },
    apiGateways: {
      userApi: '',
      backoffice: '',
      battles: '',
      participations: '',
    }
  }
};

const CONFIG = {
  environment: ENV,
  cognito: ENVIRONMENTS[ENV].cognito,
  apiGateways: ENVIRONMENTS[ENV].apiGateways,
  proxy: { port: 8081 },

  // Route mapping: which API Gateway to use for each path pattern.
  // Aggiungi qui i pattern man mano che sblocchi nuovi servizi.
  routeMapping: {
    '/auth/': 'local',

    // User API (profile, settings, fcm-token, delete-account)
    '/profile': 'userApi',
    '/settings': 'userApi',
    '/users/[^/]+/fcm-token': 'userApi',
    '/bookmarks/battles': 'userApi',

    // Battles
    '/battles': 'battles',
    '/battles/': 'battles',
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

  runAwsCli(args) {
    return new Promise((resolve, reject) => {
      const aws = spawn('aws', args);
      let stdout = '';
      let stderr = '';

      aws.stdout.on('data', (data) => stdout += data.toString());
      aws.stderr.on('data', (data) => stderr += data.toString());

      aws.on('close', (code) => {
        if (code !== 0) {
          reject(new Error(stderr || 'AWS CLI command failed'));
          return;
        }
        resolve(stdout ? JSON.parse(stdout) : {});
      });
    });
  }

  async signUp(username, password, givenName, familyName, autoConfirm = true) {
    const userAttributes = [`Name=given_name,Value=${givenName || ''}`];
    if (familyName) userAttributes.push(`Name=family_name,Value=${familyName}`);

    const signUpResult = await this.runAwsCli([
      'cognito-idp', 'sign-up',
      '--region', this.region,
      '--client-id', this.clientId,
      '--username', username,
      '--password', password,
      '--user-attributes', ...userAttributes,
      '--output', 'json'
    ]);

    if (!autoConfirm) {
      return {
        userSub: signUpResult.UserSub,
        confirmed: false,
        message: 'Account creato. Controlla la mail per il codice di verifica e usa POST /auth/confirm.'
      };
    }

    // Auto-confirma l'utente (skip del codice email) - solo per comodità in dev/test
    await this.runAwsCli([
      'cognito-idp', 'admin-confirm-sign-up',
      '--region', this.region,
      '--user-pool-id', this.userPoolId,
      '--username', username
    ]);

    return {
      userSub: signUpResult.UserSub,
      confirmed: true,
      message: 'Account creato e confermato. Ora puoi fare login con POST /auth/login/users.'
    };
  }

  async confirmSignUp(username, code) {
    await this.runAwsCli([
      'cognito-idp', 'confirm-sign-up',
      '--region', this.region,
      '--client-id', this.clientId,
      '--username', username,
      '--confirmation-code', code
    ]);

    return {
      confirmed: true,
      message: 'Account confermato. Ora puoi fare login con POST /auth/login/users.'
    };
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
        url.pathname === '/auth/login/users') {
      await this.handleLogin(req, res);
      return;
    }

    if (url.pathname === '/auth/signup') {
      await this.handleSignup(req, res);
      return;
    }

    if (url.pathname === '/auth/confirm') {
      await this.handleConfirm(req, res);
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

  async handleSignup(req, res) {
    try {
      const body = await this.readBody(req);
      const { username, password, given_name, family_name, auto_confirm } = JSON.parse(body);

      if (!username || !password) {
        this.sendError(res, 400, 'username and password required');
        return;
      }

      const autoConfirm = auto_confirm === true; // default false: rispecchia il flusso reale dell'app
      console.log(`[AUTH] Signup attempt: ${username} (auto_confirm=${autoConfirm})`);
      const result = await this.auth.signUp(username, password, given_name, family_name, autoConfirm);
      console.log(`[AUTH] Signup success: ${username}`);

      this.sendJson(res, 201, result);
    } catch (error) {
      console.error(`[AUTH] Signup failed:`, error.message);
      this.sendError(res, 400, error.message);
    }
  }

  async handleConfirm(req, res) {
    try {
      const body = await this.readBody(req);
      const { username, code } = JSON.parse(body);

      if (!username || !code) {
        this.sendError(res, 400, 'username and code required');
        return;
      }

      console.log(`[AUTH] Confirm attempt: ${username}`);
      const result = await this.auth.confirmSignUp(username, code);
      console.log(`[AUTH] Confirm success: ${username}`);

      this.sendJson(res, 200, result);
    } catch (error) {
      console.error(`[AUTH] Confirm failed:`, error.message);
      this.sendError(res, 400, error.message);
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
    return null;
  }

  proxyToApiGateway(req, res) {
    const pathname = new URL(req.url, `http://localhost:${this.config.proxy.port}`).pathname;
    const gatewayType = this.determineApiGateway(pathname);

    if (!gatewayType || gatewayType === 'local') {
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
