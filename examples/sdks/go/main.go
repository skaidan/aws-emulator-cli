// AWS SDK for Go v2 against AWS Emulator.
//
//	go mod tidy
//	awsemu exec -- go run .
//
// Nothing here knows about the emulator: the endpoint (AWS_ENDPOINT_URL), region,
// credentials and certificate (AWS_CA_BUNDLE) come from the environment awsemu sets.
// The same code runs against AWS.
package main

import (
	"context"
	"fmt"
	"io"
	"log"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

func main() {
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx)
	must(err)

	s3c := s3.NewFromConfig(cfg)
	_, err = s3c.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: aws.String("go-example")})
	must(err)
	_, err = s3c.PutObject(ctx, &s3.PutObjectInput{Bucket: aws.String("go-example"), Key: aws.String("hello.txt"),
		Body: strings.NewReader("hello from go")})
	must(err)
	obj, err := s3c.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String("go-example"), Key: aws.String("hello.txt")})
	must(err)
	body, err := io.ReadAll(obj.Body)
	must(err)
	check("s3", string(body), "hello from go")

	sqsc := sqs.NewFromConfig(cfg)
	queue, err := sqsc.CreateQueue(ctx, &sqs.CreateQueueInput{QueueName: aws.String("go-example")})
	must(err)
	_, err = sqsc.SendMessage(ctx, &sqs.SendMessageInput{QueueUrl: queue.QueueUrl, MessageBody: aws.String("job-1")})
	must(err)
	got, err := sqsc.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{QueueUrl: queue.QueueUrl, WaitTimeSeconds: 5})
	must(err)
	first := ""
	if len(got.Messages) > 0 {
		first = aws.ToString(got.Messages[0].Body)
	}
	check("sqs", first, "job-1")

	ddb := dynamodb.NewFromConfig(cfg)
	_, err = ddb.CreateTable(ctx, &dynamodb.CreateTableInput{
		TableName:            aws.String("go-example"),
		BillingMode:          ddbtypes.BillingModePayPerRequest,
		AttributeDefinitions: []ddbtypes.AttributeDefinition{{AttributeName: aws.String("id"), AttributeType: ddbtypes.ScalarAttributeTypeS}},
		KeySchema:            []ddbtypes.KeySchemaElement{{AttributeName: aws.String("id"), KeyType: ddbtypes.KeyTypeHash}},
	})
	must(err)
	must(dynamodb.NewTableExistsWaiter(ddb).Wait(ctx, &dynamodb.DescribeTableInput{TableName: aws.String("go-example")}, time.Minute))
	_, err = ddb.PutItem(ctx, &dynamodb.PutItemInput{TableName: aws.String("go-example"), Item: map[string]ddbtypes.AttributeValue{
		"id": &ddbtypes.AttributeValueMemberS{Value: "1"}, "name": &ddbtypes.AttributeValueMemberS{Value: "Ana"}}})
	must(err)
	item, err := ddb.GetItem(ctx, &dynamodb.GetItemInput{TableName: aws.String("go-example"),
		Key: map[string]ddbtypes.AttributeValue{"id": &ddbtypes.AttributeValueMemberS{Value: "1"}}})
	must(err)
	name := ""
	if v, ok := item.Item["name"].(*ddbtypes.AttributeValueMemberS); ok {
		name = v.Value
	}
	check("dynamodb", name, "Ana")
	fmt.Println("go: all checks passed")
}

func check(what, got, want string) {
	if got != want {
		log.Fatalf("%s: expected %q, got %q", what, want, got)
	}
	fmt.Println("✓ " + what)
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
