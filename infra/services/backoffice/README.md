# backoffice-api-sam

## backoffice-list-documents

1. Lista tutti i documenti in attesa di review
GET /documents?status=AWAITING_REVIEW&limit=20

2. Lista tutti i documenti di un utente
GET /documents/user/abc123-def456-789

3. Lista tutti i documenti respinti
GET /documents?status=REJECTED

4. Dashboard overview (tutti i documenti recenti)
GET /documents?limit=50

## backoffice-search-users

1. Ricerca per email
GET /users/search?type=email&q=francesco&limit=5

2. Ricerca per nome
GET /users/search?type=name&q=Francesco&limit=10

3. Filtro per status
GET /users/search?type=status&q=CONFIRMED&limit=15

4. Filtro per tipo utente
GET /users/search?type=user_type&q=guest&limit=20

5. Ricerca per età
GET /users/search?type=birthdate&q=1990-01-01,1999-12-31&limit=15

6. Utenti recenti
GET /users/search?type=recent&limit=20

## backoffice-get-document-url

1. Get document download URL
POST /documents/download/{user_sub}/{doc_id}

## backoffice-update-document-status

1. Update document status
PUT /documents/{user_sub}/{doc_id}/status

### Answer Structure
```
{
  "documents": [
    {
      "documentId": "1757399658891_id_card_front",
      "userSub": "abc123-def456-789", 
      "docType": "id_card_front",
      "timestamp": 1757399658891,
      "status": "AWAITING_REVIEW",
      "mime": "image/jpeg",
      "size": 245760,
      "uploadedAt": "2025-01-08T14:30:00Z",
      "s3Key": "docs/abc123-def456-789/1757399658891_id_card_front.jpg",
      "reason": null,
      "reviewedAt": null, 
      "reviewedBy": null
    }
  ],
  "count": 1,
  "statusFilter": "AWAITING_REVIEW"
}
```

### Testing with Events

Test Events are present under events/apigw/list-all-documents.json and events/apigw/list-user-documents.json.

Same for cors-preflight.